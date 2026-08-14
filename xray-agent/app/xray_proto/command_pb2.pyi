import user_pb2 as _user_pb2
import typed_message_pb2 as _typed_message_pb2
from google.protobuf.internal import containers as _containers
from google.protobuf import descriptor as _descriptor
from google.protobuf import message as _message
from typing import ClassVar as _ClassVar, Iterable as _Iterable, Mapping as _Mapping, Optional as _Optional, Union as _Union

DESCRIPTOR: _descriptor.FileDescriptor

class AddUserOperation(_message.Message):
    __slots__ = ("user",)
    USER_FIELD_NUMBER: _ClassVar[int]
    user: _user_pb2.User
    def __init__(self, user: _Optional[_Union[_user_pb2.User, _Mapping]] = ...) -> None: ...

class RemoveUserOperation(_message.Message):
    __slots__ = ("email",)
    EMAIL_FIELD_NUMBER: _ClassVar[int]
    email: str
    def __init__(self, email: _Optional[str] = ...) -> None: ...

class AlterInboundRequest(_message.Message):
    __slots__ = ("tag", "operation")
    TAG_FIELD_NUMBER: _ClassVar[int]
    OPERATION_FIELD_NUMBER: _ClassVar[int]
    tag: str
    operation: _typed_message_pb2.TypedMessage
    def __init__(self, tag: _Optional[str] = ..., operation: _Optional[_Union[_typed_message_pb2.TypedMessage, _Mapping]] = ...) -> None: ...

class AlterInboundResponse(_message.Message):
    __slots__ = ()
    def __init__(self) -> None: ...

class GetInboundUserRequest(_message.Message):
    __slots__ = ("tag", "email")
    TAG_FIELD_NUMBER: _ClassVar[int]
    EMAIL_FIELD_NUMBER: _ClassVar[int]
    tag: str
    email: str
    def __init__(self, tag: _Optional[str] = ..., email: _Optional[str] = ...) -> None: ...

class GetInboundUserResponse(_message.Message):
    __slots__ = ("users",)
    USERS_FIELD_NUMBER: _ClassVar[int]
    users: _containers.RepeatedCompositeFieldContainer[_user_pb2.User]
    def __init__(self, users: _Optional[_Iterable[_Union[_user_pb2.User, _Mapping]]] = ...) -> None: ...

class GetInboundUsersCountResponse(_message.Message):
    __slots__ = ("count",)
    COUNT_FIELD_NUMBER: _ClassVar[int]
    count: int
    def __init__(self, count: _Optional[int] = ...) -> None: ...
