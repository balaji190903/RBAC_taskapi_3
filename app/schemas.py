from datetime import date, datetime
from pydantic import BaseModel, ConfigDict, EmailStr, Field

from app.models import PriorityEnum, RoleEnum, StatusEnum


# --- Authentication ---
class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class Token(BaseModel):
    access_token: str
    token_type: str = "bearer"


# --- User ---
class UserBase(BaseModel):
    full_name: str = Field(min_length=1, max_length=120)
    email: EmailStr


class UserCreate(UserBase):
    password: str = Field(min_length=6, max_length=128)
    role: RoleEnum = RoleEnum.MEMBER


class UserUpdateRole(BaseModel):
    role: RoleEnum


class UserOut(UserBase):
    model_config = ConfigDict(from_attributes=True)

    id: int
    role: RoleEnum
    is_active: bool
    created_at: datetime


# --- Project ---
class ProjectBase(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    description: str | None = None


class ProjectCreate(ProjectBase):
    pass


class ProjectUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    description: str | None = None


class ProjectOut(ProjectBase):
    model_config = ConfigDict(from_attributes=True)

    id: int
    created_by: int
    created_at: datetime


class ProjectMemberAdd(BaseModel):
    user_id: int


class ProjectMemberOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    project_id: int
    user_id: int
    added_at: datetime
    user: UserOut


# --- Task ---
class TaskBase(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    description: str | None = None
    priority: PriorityEnum = PriorityEnum.MEDIUM
    due_date: date | None = None
    assigned_to: int | None = None


class TaskCreate(TaskBase):
    project_id: int


class TaskUpdateFull(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=200)
    description: str | None = None
    status: StatusEnum | None = None
    priority: PriorityEnum | None = None
    due_date: date | None = None
    assigned_to: int | None = None


class TaskUpdateStatus(BaseModel):
    status: StatusEnum


class TaskOut(TaskBase):
    model_config = ConfigDict(from_attributes=True)

    id: int
    status: StatusEnum
    project_id: int
    created_at: datetime
