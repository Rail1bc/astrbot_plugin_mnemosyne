from pymilvus import (
    connections,
    FieldSchema,
    CollectionSchema,
    DataType,
    Collection,
    utility,
)
from typing import List, Dict, Optional, Any
from datetime import datetime
import time

from ...memory_manager.vector_db_base import VectorDatabase

from astrbot.core.log import LogManager


class MilvusDatabase(VectorDatabase):
    """
    Milvus 向量数据库实现
    """

    def __init__(self, host, port):
        self.collections = {}  # 用于缓存已创建的集合实例
        self.connection_alias = "default"
        self.logger = LogManager.GetLogger(log_name="Mnemosyne MilvusDatabase")
        self.host = host
        self.port = port

    def __enter__(self):
        """上下文管理器：进入时连接数据库"""
        self.connect()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """上下文管理器：退出时关闭连接"""
        self.close()

    def close(self):
        """
        关闭数据库连接
        """
        try:
            if connections.has_connection(self.connection_alias):
                connections.disconnect(self.connection_alias)
                self.logger.info("与 Milvus 断开连接.")
        except Exception as e:
            self.logger.error(f"与 Milvus 断开连接发生错误: {e}")

    def _ensure_connection(self):
        """确保与 Milvus 的连接有效，必要时重新连接"""
        if not connections.has_connection(self.connection_alias):
            self.logger.warning("与 Milvus 的连接已断开，正在尝试重新连接...")
            self.connect()

    def connect(self):
        """
        连接到 Milvus 数据库
        """
        try:
            connections.connect(
                alias=self.connection_alias, host=self.host, port=self.port
            )
            self.logger.info(f"成功连接到 Milvus 数据库 ({self.host}:{self.port})")

            existing_collections = self.list_collections()
            self.collections.clear()  # 清空原有缓存

            for col_name in existing_collections:
                try:
                    # 确保集合存在
                    if not utility.has_collection(
                        col_name, using=self.connection_alias
                    ):
                        self.logger.debug(f"集合 '{col_name}' 不存在")
                        continue

                    # 获取集合对象
                    col = Collection(col_name)

                    # 检查集合是否有索引
                    if not col.indexes:
                        self.logger.warning(f"集合 '{col_name}' 没有索引，跳过加载")
                        continue

                    # 加载集合到内存
                    col.load()
                    self.logger.debug(f"集合 '{col_name}' 已成功加载到内存")

                    # 缓存集合对象
                    self.collections[col_name] = col

                except Exception as e:
                    self.logger.error(f"加载集合 '{col_name}' 失败: {e}")
                    continue  # 如果某个集合加载失败，继续处理下一个集合

        except Exception as e:
            self.logger.error(f"连接 Milvus 数据库失败: {e}")
            raise

    def _get_collection(self, collection_name: str) -> Collection:
        """统一获取集合实例并检查加载状态"""
        col = self.collections.get(collection_name)
        if not col:
            if not utility.has_collection(collection_name):
                raise ValueError(f"Collection '{collection_name}' does not exist.")
            col = Collection(collection_name)
            self.collections[collection_name] = col

        # 检查集合是否已加载
        load_state = utility.load_state(collection_name)
        if load_state != "Loaded":
            self.logger.info(
                f"Collection '{collection_name}' is not loaded. Loading now..."
            )
            col.load()  # 加载集合
        return col

    def create_collection(self, collection_name: str, schema: Dict[str, Any]):
        """
        创建集合（表）
        :param collection_name: 集合名称
        :param schema: 集合的字段定义
        """
        try:
            # 检查集合是否已存在
            if utility.has_collection(collection_name, using=self.connection_alias):
                self.logger.info(f"集合 '{collection_name}' 已被创建.")
                return

            # 构建字段列表
            fields = []
            for field_definition in schema["fields"]:
                field_name = field_definition["name"]
                field_type = field_definition["dtype"]
                is_primary = field_definition.get("is_primary", False)
                auto_id = field_definition.get("auto_id", False)
                is_nullable = field_definition.get("is_nullable", False)

                # 特殊处理：VARCHAR 和 FLOAT_VECTOR
                if field_type == DataType.VARCHAR:
                    max_length = field_definition["max_length"]
                    fields.append(
                        FieldSchema(
                            name=field_name,
                            dtype=field_type,
                            max_length=max_length,
                            is_primary=is_primary,
                            auto_id=auto_id,
                        )
                    )
                elif field_type == DataType.FLOAT_VECTOR:
                    dim = field_definition["dim"]
                    fields.append(
                        FieldSchema(name=field_name, dtype=field_type, dim=dim)
                    )
                else:
                    fields.append(
                        FieldSchema(
                            name=field_name,
                            dtype=field_type,
                            is_primary=is_primary,
                            auto_id=auto_id,
                            is_nullable=is_nullable,
                        )
                    )

            # 创建集合的 Schema
            collection_schema = CollectionSchema(
                fields, description=schema.get("description", "")
            )

            # 创建集合
            self.collections[collection_name] = Collection(
                name=collection_name,
                schema=collection_schema,
                using=self.connection_alias,
            )
            self.logger.info(f"集合 '{collection_name}' 创建成功.")

            # 为向量字段创建索引
            for field_definition in schema["fields"]:
                if field_definition["dtype"] == DataType.FLOAT_VECTOR:
                    index_params = field_definition.get("index_params", {})
                    if not index_params:
                        self.logger.warning(f"未提供索引参数，默认使用 IVF_FLAT 索引.")
                        index_params = {
                            "index_type": "IVF_FLAT",
                            "metric_type": "L2",
                            "params": {"nlist": 256},
                        }

                    # 创建索引
                    self.logger.info(
                        f"正在为字段 '{field_definition['name']}' 创建索引..."
                    )
                    self.collections[collection_name].create_index(
                        field_name=field_definition["name"], index_params=index_params
                    )
                    self.logger.info(
                        f"字段 '{field_definition['name']}' 的索引创建成功."
                    )

            # 刷新集合以确保数据一致性
            self.collections[collection_name].flush()
            return

        except Exception as e:
            self.logger.error(f"创建集合失败: {e}")

    def insert(self, collection_name: str, data: List[Dict[str, Any]]):
        try:
            self._ensure_connection()  # 确保连接有效
            col = self._get_collection(collection_name)

            # 自动添加时间戳
            current_time = int(time.time())
            for item in data:
                if "create_time" not in item:
                    item["create_time"] = current_time

            # 打印调试信息
            # self.logger.debug(f"准备插入的 field_data: {data}")

            col.insert(data[0])
            col.flush()  # 确保数据持久化
            self.logger.info(f"插入数据成功：{len(data)} .")

        except Exception as e:
            self.logger.error(f"插入数据失败: {e}")

    def query(
        self, collection_name: str, filters: str, output_fields: List[str]
    ) -> List[Dict[str, Any]]:
        """
        根据条件查询数据
        :param collection_name: 集合名称
        :param filters: 查询条件表达式
        :param output_fields: 返回的字段列表
        :return: 查询结果
        """
        try:
            self._ensure_connection()  # 确保连接有效
            collection = self.collections.get(collection_name)
            if not collection:
                raise ValueError(f"集合 '{collection_name}' 不存在.")

            collection.load()

            results = collection.query(expr=filters, output_fields=output_fields)
            return results  # 直接返回查询结果，query 结果通常是可迭代的
        except Exception as e:
            self.logger.error(f"条件查询失败: {e}")
            return []

    def search(
        self,
        collection_name: str,
        query_vector: List[float],
        top_k: int,
        filters: str = None,
    ) -> List[Dict[str, Any]]:
        """
        执行相似性搜索
        :param collection_name: 集合名称
        :param query_vector: 查询向量
        :param top_k: 返回的最相似结果数量
        :param filters: 可选的过滤条件
        :return: 搜索结果
        """
        try:
            self._ensure_connection()
            collection = self.collections.get(collection_name)
            if not collection:
                raise ValueError(f"集合 '{collection_name}' 不存在.")

            collection.load()

            search_params = {"metric_type": "L2", "params": {"nprobe": 10}}
            results = collection.search(
                data=[query_vector],
                anns_field="embedding",
                param=search_params,
                limit=top_k,
                expr=filters,
            )
            result_list = []
            for hits in results:  # 遍历每个查询向量的搜索结果
                for hit in hits:
                    # 替换此处开始
                    # 增强类型检查和错误处理
                    if not all(
                        hasattr(hit, attr) for attr in ["id", "distance", "entity"]
                    ):
                        self.logger.warning(
                            f"无效的搜索结果对象类型: {type(hit)} | 内容: {hit}"
                        )
                        continue

                    try:
                        entity_dict = (
                            hit.entity.to_dict()
                            if hasattr(hit.entity, "to_dict")
                            else dict(hit.entity)
                        )
                        result_list.append(
                            {
                                "id": hit.id,
                                "distance": hit.distance,
                                "entity": entity_dict,
                            }
                        )
                    except AttributeError as ae:
                        self.logger.error(
                            f"实体解析失败 - 缺少属性: {ae} | 数据: {hit}"
                        )
                    except Exception as e:
                        self.logger.error(
                            f"处理搜索结果时发生意外错误: {e} | 数据: {hit}"
                        )
                    # 替换此处结束
            return result_list
        except Exception as e:
            self.logger.error(f"相似度搜索失败: {e}")
            return []

    def list_collections(self) -> List[str]:
        """获取所有集合名称"""
        try:
            return utility.list_collections()
        except Exception as e:
            self.logger.error(f"未能列出集合: {e}")
            return []

    def get_loaded_collections(self) -> List[str]:
        """获取已加载到内存的集合"""
        loaded = []
        for name in self.list_collections():
            col = Collection(name)
            if col.load_state == "Loaded":
                loaded.append(name)
        return loaded

    def get_latest_memory(
        self, collection_name: str, limit: int
    ) -> List[Dict[str, Any]]:
        """获取最新插入的记忆"""
        try:
            # 使用 _get_collection 方法确保集合已加载到内存
            collection = self._get_collection(collection_name)

            # 按时间戳降序获取最新记录（修正排序参数格式）
            results = collection.query(
                expr="",
                output_fields=["*"],
                sort_by=("create_time", "desc"),
                limit=limit,
            )

            # 安全处理空结果
            return results if results else []

        except ValueError as ve:
            self.logger.error(f"集合不存在: {ve}")
            return []

        except IndexError:
            self.logger.warning(f"集合 '{collection_name}' 中没有数据")
            return []

        except Exception as e:
            self.logger.error(f"获取最新的记忆失败: {e}")
            return []

    def delete(self, collection_name: str, expr: str):
        """根据条件删除记忆"""
        try:
            collection = self.collections.get(collection_name)
            if not collection:
                raise ValueError(f"Collection '{collection_name}' does not exist.")

            # 执行删除操作
            collection.delete(expr=expr)
            self.logger.info(f"删除匹配记录: {expr}")
        except Exception as e:
            self.logger.error(f"删除失败: {e}")

    def drop_collection(self, collection_name: str) -> None:
        """
        删除指定的集合（包括其下的所有数据）

        :param collection_name: 要删除的集合名称
        """
        try:
            if not utility.has_collection(collection_name):
                self.logger.warning(f"尝试删除不存在的集合 '{collection_name}'")
                return

            # 从内存中卸载集合
            if collection_name in self.collections:
                self.collections[collection_name].release()

            # 使用Pymilvus API删除集合
            utility.drop_collection(collection_name)

            # 从本地缓存中移除集合引用
            if collection_name in self.collections:
                del self.collections[collection_name]

            self.logger.info(f"成功删除集合 '{collection_name}' 及其下的所有数据.")
        except Exception as e:
            self.logger.error(f"删除集合时发生错误: {e}")

    def check_collection_schema_consistency(
        self, collection_name: str, expected_schema: Dict[str, Any]
    ):
        """
        检查集合的 Schema 是否与预期一致
        :param collection_name: 集合名称
        :param expected_schema: 预期的 Schema 定义
        :return: True 如果一致，False 如果不一致
        """
        try:
            self._ensure_connection()  # 确保连接有效

            # 检查集合是否存在
            if not utility.has_collection(collection_name, using=self.connection_alias):
                self.logger.warning(f"集合 '{collection_name}' 不存在，无法检查一致性.")
                return False

            # 获取集合的现有 Schema
            collection = Collection(collection_name)
            existing_fields = {field.name: field for field in collection.schema.fields}

            # 边界条件：如果现有字段为空
            if not existing_fields and expected_schema["fields"]:
                self.logger.warning(
                    f"集合 '{collection_name}' 没有任何字段，无法与预期 Schema 匹配."
                )
                return False

            # 边界条件：如果预期字段为空
            if not expected_schema["fields"]:
                self.logger.warning(
                    f"预期 Schema 的字段定义为空，无法与集合 '{collection_name}' 匹配."
                )
                return False

            # 提取字段一致性检查逻辑
            def check_field(
                field_definition: Dict[str, Any], existing_fields: Dict[str, Any]
            ) -> bool:
                field_name = field_definition["name"]
                field_dtype = field_definition["dtype"]

                # 检查字段是否存在
                if field_name not in existing_fields:
                    self.logger.warning(
                        f"集合 '{collection_name}' 缺少字段 '{field_name}'."
                    )
                    return False

                existing_field = existing_fields[field_name]

                # 检查字段类型是否一致
                if existing_field.dtype != field_dtype:
                    self.logger.warning(
                        f"集合 '{collection_name}' 字段 '{field_name}' 的数据类型不匹配. "
                        f"期望: {field_dtype}, 实际: {existing_field.dtype}."
                    )
                    return False

                # 特殊处理：VARCHAR 和 FLOAT_VECTOR
                if field_dtype == DataType.VARCHAR:
                    expected_max_length = field_definition.get("max_length", None)
                    actual_max_length = getattr(existing_field, "max_length", None)
                    if expected_max_length != actual_max_length:
                        self.logger.warning(
                            f"集合 '{collection_name}' 字段 '{field_name}' 的最大长度不匹配. "
                            f"期望: {expected_max_length}, 实际: {actual_max_length}."
                        )
                        return False
                elif field_dtype == DataType.FLOAT_VECTOR:
                    expected_dim = field_definition.get("dim", None)
                    actual_dim = existing_field.params.get("dim", None)
                    if expected_dim != actual_dim:
                        self.logger.warning(
                            f"集合 '{collection_name}' 字段 '{field_name}' 的维度不匹配. "
                            f"期望: {expected_dim}, 实际: {actual_dim}."
                        )
                        return False
                return True

            # 遍历预期的字段定义
            for field_definition in expected_schema["fields"]:
                if not check_field(field_definition, existing_fields):
                    return False

            # 检查是否有额外的字段
            expected_field_names = {
                field["name"] for field in expected_schema["fields"]
            }
            extra_fields = set(existing_fields.keys()) - expected_field_names
            if extra_fields:
                self.logger.warning(
                    f"集合 '{collection_name}' 包含多余的字段: {extra_fields}."
                )
                return False

            self.logger.info(f"集合 '{collection_name}' 的结构与预期一致.")
            return True

        except ConnectionError as ce:
            self.logger.error(f"连接数据库时发生错误: {ce}")
            return False
        except KeyError as ke:
            self.logger.error(f"Schema 定义中缺少关键字段: {ke}")
            return False
        except Exception as e:
            self.logger.error(f"检查集合结构一致性时发生未知错误: {e}")
            return False
