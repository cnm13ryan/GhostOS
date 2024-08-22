from typing import Optional, List, Iterable
import time
from abc import ABC, abstractmethod
from pydantic import BaseModel, Field
from ghostiss.core.messages import Message, copy_messages, DefaultMessageTypes
from ghostiss.core.moss.pycontext import PyContext
from ghostiss.core.llms import Chat
from ghostiss.core.session.events import Event
from ghostiss.helpers import uuid
from contextlib import contextmanager

__all__ = [
    'Threads', 'MsgThread',
    'thread_to_chat',
]


class Turn(BaseModel):
    """
    single turn in the thread
    """
    turn_id: str = Field(
        default_factory=uuid,
        description="id of the turn"
    )
    event: Optional[Event] = Field(
        default=None,
        description="event of the turn"
    )
    generates: List[Message] = Field(
        default_factory=list,
        description="The new messages that generated by ghost during this turn of chat or thinking."
                    "Shall append to messages after updating.",
    )
    pycontext: PyContext = Field(
        default_factory=PyContext,
        description="The PyContext instance",
    )
    created: float = Field(
        default_factory=lambda: round(time.time(), 4),
    )

    @classmethod
    def new(cls, event: Optional[Event], *, turn_id: Optional[str] = None,
            pycontext: Optional[PyContext] = None) -> "Turn":
        data = {"event": event}
        turn_id = turn_id if turn_id else event.id
        data["turn_id"] = turn_id
        if pycontext is not None:
            data["pycontext"] = pycontext
        return cls(**data)

    def append(self, *messages: Message, pycontext: Optional[PyContext] = None) -> None:
        self.generates.extend(messages)
        if pycontext is not None:
            self.pycontext = pycontext

    def messages(self) -> Iterable[Message]:
        event = self.event
        if event is not None:
            if event.from_self() and not event.no_reason_or_instruction():
                # todo: 将 event 和历史消息的关联建立起来. 类似 tool id 的方式.
                contents = [
                    f"receive self event `{event.type}`",
                    f"\n- reason: {event.reason}" if event.reason else "",
                    f"\n- instruction: {event.instruction}" if event.instruction else "",
                ]
                content = "".join(contents)
                # 暂时考虑用系统消息来标记事件.
                yield DefaultMessageTypes.DEFAULT.new_system(content=content)
            elif event.from_task_id is not None:
                # todo: 考虑未来应该怎么优化. task_id 如果是 uuid 的话, 多少有一些问题.
                contents = [
                    f"from task {event.from_task_id} receive event `{event.type}`.",
                    f"\n- reason: {event.reason}" if event.reason else "",
                    f"\n- instruction: {event.instruction}" if event.instruction else "",
                ]
                content = "".join(contents)
                # 暂时考虑用系统消息来标记事件.
                yield DefaultMessageTypes.DEFAULT.new_system(content=content)
            # 携带的消息体.
            for message in self.event.messages:
                yield message

        if self.generates:
            yield from self.generates


class MsgThread(BaseModel):
    """
    对话历史.
    存储时应该使用别的数据结构.
    """
    id: str = Field(
        default_factory=uuid,
        description="The id of the thread, also a fork id",
    )
    root_id: Optional[str] = Field(
        default=None,
        description="The id of the root thread if the thread is a fork",
    )
    parent_id: Optional[str] = Field(
        default=None,
        description="The id of the parent thread if the thread is a fork",
    )
    on_created: Turn = Field(
        default_factory=Turn,
        description="the turn that thread was created",
    )
    history: List[Turn] = Field(
        default_factory=list,
        description="the history turns"
    )
    current: Optional[Turn] = Field(
        default=None,
        description="the current turn",
    )

    @classmethod
    def new(
            cls,
            event: Optional[Event],
            *,
            pycontext: Optional[PyContext] = None,
            thread_id: Optional[str] = None,
            root_id: Optional[str] = None,
            parent_id: Optional[str] = None,
    ) -> "MsgThread":
        """
        初始化一个 Thread.
        :param event: 首轮输入的信息.
        :param pycontext: 初始化时的 pycontext.
        :param thread_id: 指定的 thread id.
        :param root_id: 指定的 root id.
        :param parent_id: 任务的 parent id.
        :return:
        """

        data = {
            "on_created": Turn.new(event=event, turn_id=thread_id, pycontext=pycontext),
        }
        if thread_id is not None:
            data["thread_id"] = thread_id
        if root_id is not None:
            data["root_id"] = root_id
        if parent_id is not None:
            data["parent_id"] = parent_id
        return MsgThread(**data)

    def last_turn(self) -> Turn:
        """
        返回历史最后一个回合的数据.
        """
        if self.current is not None:
            return self.current
        if len(self.history) > 0:
            return self.history[-1]
        return self.on_created

    def get_history_messages(self) -> Iterable[Message]:
        """
        返回所有的历史消息.
        """
        yield from self.on_created.messages()
        if self.history:
            for turn in self.history:
                yield from turn.messages()

    def get_pycontext(self) -> PyContext:
        """
        返回最后一轮的 pycontext.
        """
        return self.last_turn().pycontext

    def update_pycontext(self, pycontext: PyContext) -> None:
        if self.current is None:
            self.new_turn(None)
        self.current.pycontext = pycontext

    def update_history(self) -> "MsgThread":
        """
        更新 thread 的 current turn 到 history turns.
        :return:
        """
        if self.current is None:
            return self
        copied = self.model_copy(deep=True)
        if copied.current is not None:
            copied.history.append(copied.current)
            copied.current = None
        return copied

    def turns(self) -> Iterable[Turn]:
        """
        遍历所有的 turns.
        """
        yield self.on_created
        if self.history:
            for turn in self.history:
                yield turn
        if self.current is not None:
            yield self.current

    def new_turn(
            self,
            event: Optional[Event],
            *,
            turn_id: Optional[str] = None,
            pycontext: Optional[PyContext] = None,
    ) -> None:
        """
        新建一个 turn 到 current turn.
        :param event: 用事件来创建回合.
        :param turn_id:
        :param pycontext:
        """
        if self.current is not None:
            self.history.append(self.current)
            self.current = None
        if pycontext is None:
            last_turn = self.last_turn()
            pycontext = last_turn.pycontext
        turn_id = turn_id or event.id
        new_turn = Turn.new(event=event, turn_id=turn_id, pycontext=pycontext)
        self.current = new_turn

    def append(self, *messages: Message, pycontext: Optional[PyContext] = None) -> None:
        """
        添加新的消息体.
        :param messages:
        :param pycontext:
        :return:
        """
        if self.current is None:
            self.new_turn(None)
        if messages:
            self.current.append(*messages)
        if pycontext:
            self.current.pycontext = pycontext

    def get_generates(self) -> List[Message]:
        if self.current is None:
            return []
        return self.current.generates

    def get_current_event(self) -> Optional[Event]:
        if self.current is None:
            return None
        return self.current.event

    def fork(self, tid: Optional[str] = None) -> "MsgThread":
        tid = tid if tid else uuid()
        root_id = self.root_id if self.root_id else self.id
        parent_id = self.id
        thread = self.model_copy(update=dict(id=tid, root_id=root_id, parent_id=parent_id), deep=True)
        return thread

    def thread_copy(self, update: Optional[dict] = None) -> "MsgThread":
        return self.model_copy(update=update, deep=True)


def thread_to_chat(chat_id: str, system: List[Message], thread: MsgThread) -> Chat:
    """
    将 thread 转换成基准的 chat.
    :param chat_id:
    :param system:
    :param thread:
    :return:
    """
    history = list(thread.get_history_messages())
    current_turn = thread.current
    inputs = current_turn.inputs if current_turn is not None else []
    appending = current_turn.generates if current_turn is not None else []

    chat = Chat(
        id=chat_id,
        system=system,
        history=copy_messages(history),
        inputs=copy_messages(inputs),
        appending=copy_messages(appending),
    )
    return chat


class Threads(ABC):
    """
    管理 Threads 存取的模块. 通常集成到 Session 里.
    """

    @abstractmethod
    def with_namespace(self, namespace: str) -> "Threads":
        pass

    @abstractmethod
    def get_thread(self, thread_id: str, create: bool = False) -> Optional[MsgThread]:
        """
        获取一个 Thread 实例. 如果不存在的话, 返回 None.
        :param thread_id: thread_id
        :param create: 如果
        :return:
        """
        pass

    @abstractmethod
    def save_thread(self, thread: MsgThread) -> None:
        pass

    @abstractmethod
    def fork_thread(self, thread: MsgThread) -> MsgThread:
        pass

    @contextmanager
    def transaction(self):
        yield
