import enum
import time
from typing import Optional, Dict, Set, Iterable, Union, List, ClassVar
from abc import ABC
from pydantic import BaseModel, Field
from ghostiss.helpers import uuid

__all__ = [
    "Message", "Role", "DefaultTypes",
    "MessageClass",
    "MessageType", "MessageTypeParser",
    "FunctionalToken",
    "Payload", "Attachment", "Caller",
]


class Role(str, enum.Enum):
    """
    消息体的角色, 对齐了 OpenAI
    """

    USER = "user"
    ASSISTANT = "assistant"
    SYSTEM = "system"
    FUNCTION = "function"

    @classmethod
    def all(cls) -> Set[str]:
        return set(map(lambda x: x.value, cls))


class DefaultTypes(str, enum.Enum):
    DEFAULT = ""
    CHAT_COMPLETION = "chat_completion"
    ERROR = "error"
    FINAL = "final"

    def new(
            self, *,
            content: str, role: str = Role.ASSISTANT.value, memory: Optional[str] = None, name: Optional[str] = None,
    ) -> "Message":
        return Message(content=content, memory=memory, name=name, type=self.value, role=role)

    def new_assistant(
            self, *,
            content: str, memory: Optional[str] = None, name: Optional[str] = None,
    ):
        return self.new(content=content, role=Role.ASSISTANT.value, memory=memory, name=name)

    def new_system(
            self, *,
            content: str, memory: Optional[str] = None,
    ):
        return self.new(content=content, role=Role.SYSTEM.value, memory=memory)

    def new_user(
            self, *,
            content: str, memory: Optional[str] = None, name: Optional[str] = None,
    ):
        return self.new(content=content, role=Role.USER.value, memory=memory, name=name)

    def match(self, message: "Message") -> bool:
        return message.type == self.value

    @classmethod
    def final(cls):
        return Message(type=cls.FINAL.value, role=Role.ASSISTANT.value)

    @classmethod
    def is_final(cls, pack: "Message") -> bool:
        return pack.type == cls.FINAL.value

    @classmethod
    def is_protocol_type(cls, message: "Message"):
        return not message.pack and message.type in {cls.ERROR, cls.FINAL}


class Caller(BaseModel):
    """
    消息协议中用来描述一个工具或者function 的调用请求.
    """
    id: Optional[str] = Field(default=None, description="caller 的 id, 用来 match openai 的 tool call 协议. ")
    name: str = Field(description="方法的名字.")
    arguments: str = Field(description="方法的参数. ")
    protocol: bool = Field(default=True, description="caller 是否是基于协议生成的?")

    def add(self, message: "Message") -> None:
        message.callers.append(self)


class FunctionalToken(BaseModel):
    """
    定义特殊的 token, 用来在流式输出中生成 caller.
    """

    id: Optional[str] = Field(default=None, description="用来生成 caller 的 id.")
    token: str = Field(description="流式输出中标志 caller 的特殊 token. 比如 :moss>\n ")
    caller: str = Field(description="caller 的名字. ")
    description: str = Field(description="functional token 的描述")
    deliver: bool = Field(description="functional token 后续的信息是否要发送. 可以设置不发送. ")

    def new_caller(self, arguments: str) -> "Caller":
        return Caller(
            id=self.id,
            name=self.caller,
            arguments=arguments,
            protocol=False,
        )


class Payload(BaseModel, ABC):
    """
    消息体的可扩展的部分. 拥有强类型设计.
    """
    key: ClassVar[str]

    @classmethod
    def read(cls, message: "Message") -> Optional["Payload"]:
        value = message.payloads.get(cls.key, None)
        if value is None:
            return None
        return cls(**value)

    def set(self, message: "Message") -> None:
        message.payloads[self.key] = self.model_dump()

    def exists(self, message: "Message") -> bool:
        return self.key in message.payloads


class Attachment(BaseModel, ABC):
    """
    消息上可以追加的附件.
    """
    key: ClassVar[str]

    @classmethod
    def read(cls, message: "Message") -> Optional[List["Attachment"]]:
        value = message.attachments.get(cls.key, None)
        if not value:
            return None
        result = []
        for item in value:
            result.append(cls(**item))
        return result

    def add(self, message: "Message") -> None:
        values = message.attachments.get(self.key)
        if values is None:
            values = []
        values.append(self.model_dump())
        message.attachments[self.key] = values


class Message(BaseModel):
    """
    消息体的容器. 通用的抽象设计, 设计思路:
    1. message 可以是一个完整的消息, 也可以是一个包, 用 pack 字段做区分. 支持 dict 传输, dict 传输时不包含默认值.
    2. 完整的 message 需要有 msg_id, 但包可以没有.
    3. content 是对客户端展示用的消息体, 而 memory 是对大模型展示的消息体. 两者可能不一样.
    4. message 可以有强类型字段, 比如 images, 但通过 attachments (累加) 和 payload (替代) 来定义. Message 容器里放弱类型的 dict.
    5. type 字段用来提示 message 拥有的信息. 比如 images 消息, 会包含 images payload, 但同时也会指定 type. 这样方便解析时预判.
    6. 所有的 message 都需要能转换成模型的协议, 默认要对齐 openai 的协议.
    7. openai 协议中的 tool, function_call 统一成 caller 抽象, 通过 caller.id 来做区分.
    8. 流式传输中, 可以有首包和尾包. 首包期待包含全部的 payloads 和 attachments. 间包则可选. 尾包是完整的消息体.
    """

    msg_id: str = Field(default="", description="消息的全局唯一 id. ")
    type: str = Field(default="", description="消息类型是对 payload 的约定. 默认的 type就是 text.")
    created: int = Field(default=0, description="Message creation time")
    pack: bool = Field(default=True, description="Message reset time")

    role: str = Field(default=Role.ASSISTANT.value, description="Message role", enum=Role.all())
    name: Optional[str] = Field(default=None, description="Message sender name")

    content: Optional[str] = Field(default=None, description="Message content")
    memory: Optional[str] = Field(default=None, description="Message memory")

    # --- attachments --- #

    payloads: Dict[str, Dict] = Field(default_factory=dict, description="k/v 结构的强类型参数.")
    attachments: Dict[str, List[Dict]] = Field(default_factory=dict, description="k/list[v] 类型的强类型参数.")

    callers: List[Caller] = Field(default_factory=list, description="将 callers 作为一种单独的类型. ")

    @classmethod
    def new_head(
            cls, *,
            role: str = Role.ASSISTANT.value,
            typ: str = "",
            content: Optional[str] = None,
            memory: Optional[str] = None,
            name: Optional[str] = None,
            msg_id: Optional[str] = None,
            created: int = 0,
    ):
        if msg_id is None:
            msg_id = uuid()
        if created <= 0:
            created = int(time.time())
        return cls(
            role=role, name=name, content=content, memory=memory, pack=True,
            type=typ,
            msg_id=msg_id, created=created,
        )

    @classmethod
    def new_tail(
            cls, *,
            role: str = Role.ASSISTANT.value,
            typ: str = "",
            content: Optional[str] = None,
            memory: Optional[str] = None,
            name: Optional[str] = None,
            msg_id: Optional[str] = None,
            created: int = 0,
    ):

        msg = cls.new_head(
            role=role, name=name, content=content, memory=memory,
            typ=typ,
            msg_id=msg_id, created=created,
        )
        msg.pack = False
        return msg

    @classmethod
    def new_pack(
            cls, *,
            typ: str = "",
            role: str = Role.ASSISTANT.value,
            content: Optional[str] = None,
            memory: Optional[str] = None,
            name: Optional[str] = None,
    ):
        return cls(
            role=role, name=name, content=content, memory=memory, pack=True,
            typ=typ,
        )

    def get_content(self) -> Optional[str]:
        if self.memory is None:
            return self.content
        return self.memory

    def patch(self, pack: "Message") -> Optional["Message"]:
        """
        预期目标消息是当前消息的一个后续包, 执行粘包逻辑.
        :param pack:
        :return: 如果粘包成功, 返回粘包后的消息. 粘包失败, 则返回 None.
        """
        #  type 不相同的话, 则认为是不同消息.
        if pack.get_type() != self.get_type():
            return None
        # 如果两个消息的 msg id 都存在, 又不相同, 则认为是不同的消息.
        if pack.msg_id and self.msg_id and pack.msg_id != self.msg_id:
            return None
        # 如果目标包是一个尾包, 则直接返回这个尾包.
        if not pack.pack:
            return pack
        # 否则更新当前消息.
        self.update(pack)
        return self

    def get_copy(self) -> "Message":
        return self.model_copy()

    def update(self, pack: "Message") -> None:
        """
        使用目标消息更新当前消息.
        """
        if not self.msg_id:
            # 当前消息的 msg id 不会变更.
            self.msg_id = pack.msg_id
        if not self.type:
            # type 也不会变更.
            self.type = pack.type
        if not self.role:
            self.role = pack.role
        if self.name is None:
            self.name = pack.name

        if self.content is None:
            self.content = pack.content
        elif pack.content is not None:
            self.content += pack.content

        if pack.memory is not None:
            self.memory = pack.memory

        self.payloads.update(pack.payloads)

        if pack.attachments is not None:
            for key, items in pack.attachments.items():
                saved = self.attachments.get(key, [])
                saved.append(*items)
                self.attachments[key] = saved
        if pack.callers:
            self.callers.extend(pack.callers)

    def get_type(self) -> str:
        """
        返回消息的类型.
        """
        return self.type or DefaultTypes.DEFAULT

    def is_empty(self) -> bool:
        """
        根据协议判断是不是空消息.
        """
        no_content = not self.content and not self.memory
        no_payloads = not self.payloads and not self.attachments and not self.callers
        no_id = not self.msg_id
        return no_id and no_content and no_payloads

    def dump(self) -> Dict:
        """
        将消息以 dict 形式输出, 过滤掉默认值.
        """
        return self.model_dump(exclude_defaults=True)


class MessageClass(ABC):
    """
    一种特殊的 Message, 本体是别的数据结构, 但可以通过 to_messages 方法生成一条或多条消息.
    """

    def to_messages(self) -> Iterable[Message]:
        pass


MessageType = Union[Message, MessageClass, str]
"""将三种类型的数据统一视作 message 类型. """


class MessageTypeParser:
    """
    处理 MessageType
    """

    def __init__(self, role: str = Role.ASSISTANT.value) -> None:
        self.role = role

    def parse(self, messages: Iterable[MessageType]) -> Iterable[Message]:
        for item in messages:
            if isinstance(item, Message):
                yield item
            if isinstance(item, MessageClass):
                yield from item.to_messages()
            if isinstance(item, str):
                yield Message.new_tail(content=item, role=self.role)
            else:
                # todo: 需要日志?
                pass

    def unknown(self, item) -> None:
        """
        unknown 消息类型的处理逻辑.
        默认忽视, 可以重写这个方法.
        """
        return