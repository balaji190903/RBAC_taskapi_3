from typing import Generator
from fastapi import Depends, FastAPI, HTTPException, Query, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.security import OAuth2PasswordBearer
from starlette.exceptions import HTTPException as StarletteHTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import Base, engine, get_db
from app.models import User, Project, ProjectMember, Task, ActivityLog, RoleEnum, StatusEnum, PriorityEnum
from app.schemas import (
    Token, UserOut, UserCreate, UserUpdateRole,
    ProjectOut, ProjectCreate, ProjectUpdate, ProjectMemberAdd, ProjectMemberOut,
    TaskOut, TaskCreate, TaskUpdateFull
)
from app.security import verify_password, create_access_token, decode_access_token, hash_password

# Automatically create tables on start. 
Base.metadata.create_all(bind=engine)

app = FastAPI(
    title="Project Management API with RBAC",
    description=(
        "A simplified Project Management API with Role-Based Access Control (RBAC). "
        "Roles: Admin, Manager, Member. Sign up at /auth/signup, login at /auth/login, "
        "and authenticate via Bearer token in Swagger UI (/docs)."
    ),
    version="1.0.0",
)


# --- Custom Exception Handlers ---
@app.exception_handler(StarletteHTTPException)
async def http_exception_handler(request, exc):
    return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail})


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request, exc):
    return JSONResponse(status_code=422, content={"detail": exc.errors()})


# --- Authentication Security Dependencies ---
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/auth/login")


def get_current_user(token: str = Depends(oauth2_scheme), db: Session = Depends(get_db)) -> User:
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    payload = decode_access_token(token)
    if payload is None:
        raise credentials_exception
    user_id = payload.get("sub")
    if user_id is None:
        raise credentials_exception
    user = db.get(User, int(user_id))
    if user is None or not user.is_active:
        raise credentials_exception
    return user


def require_roles(*roles: RoleEnum):
    """Dependency factory: raises 403 unless the current user's role is in `roles`."""
    def _checker(current_user: User = Depends(get_current_user)) -> User:
        if current_user.role not in roles:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Role '{current_user.role.value}' is not permitted to perform this action.",
            )
        return current_user
    return _checker


require_admin = require_roles(RoleEnum.ADMIN)
require_admin_or_manager = require_roles(RoleEnum.ADMIN, RoleEnum.MANAGER)


# --- Database CRUD Helpers ---
def log_activity(db: Session, user_id: int | None, action: str, detail: str | None = None) -> None:
    entry = ActivityLog(user_id=user_id, action=action, detail=detail)
    db.add(entry)
    db.commit()


def create_project(db: Session, project_in: ProjectCreate, creator: User) -> Project:
    project = Project(
        name=project_in.name,
        description=project_in.description,
        created_by=creator.id,
    )
    db.add(project)
    db.commit()
    db.refresh(project)
    db.add(ProjectMember(project_id=project.id, user_id=creator.id))
    db.commit()
    return project


def is_member(db: Session, project_id: int, user_id: int) -> bool:
    return db.scalar(
        select(ProjectMember).where(
            ProjectMember.project_id == project_id,
            ProjectMember.user_id == user_id,
        )
    ) is not None


# --- General / Health Check ---
@app.get("/", tags=["Health Check"])
def health_check():
    return {"status": "ok", "service": "this api is working properly here ."}


# --- Auth Routes ---
@app.post("/auth/signup", response_model=UserOut, status_code=status.HTTP_201_CREATED, tags=["Authentication"])
def signup(user_in: UserCreate, db: Session = Depends(get_db)):
    if db.scalar(select(User).where(User.email == user_in.email)):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Email already registered")

    user = User(
        full_name=user_in.full_name,
        email=user_in.email,
        password=hash_password(user_in.password),
        role=RoleEnum.MEMBER,
    )
    db.add(user)
    db.commit()
    db.refresh(user)

    log_activity(db, user.id, "SIGNUP", f"New user registered: {user.email}")
    return user


@app.post("/auth/login", response_model=Token, tags=["Authentication"])
async def login(request: Request, db: Session = Depends(get_db)):
    try:
        body = await request.json()
        username = body.get("username")
        password = body.get("password")
    except Exception:
        form = await request.form()
        username = form.get("username")
        password = form.get("password")

    if not username or not password:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="username and password are required",
        )

    user = db.scalar(select(User).where(User.email == username))
    if not user or not verify_password(password, user.password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect email or password",
            headers={"WWW-Authenticate": "Bearer"},
        )
    if not user.is_active:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="User account is inactive")

    access_token = create_access_token(subject=str(user.id), extra_claims={"role": user.role.value})
    log_activity(db, user.id, "LOGIN", f"User logged in: {user.email}")
    return Token(access_token=access_token)


@app.get("/auth/me", response_model=UserOut, tags=["Authentication"])
def read_me(current_user: User = Depends(get_current_user)):
    return current_user


# --- User Management Routes (Admin Only) ---
@app.get("/users", response_model=list[UserOut], tags=["User Management (Admin)"])
def get_all_users(
    skip: int = 0,
    limit: int = 100,
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin),
):
    return list(db.scalars(select(User).offset(skip).limit(limit)))


@app.put("/users/{user_id}/role", response_model=UserOut, tags=["User Management (Admin)"])
def change_user_role(
    user_id: int,
    payload: UserUpdateRole,
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin),
):
    user = db.get(User, user_id)
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    user.role = payload.role
    db.commit()
    db.refresh(user)

    log_activity(db, admin.id, "UPDATE_USER_ROLE", f"User {user_id} role set to {payload.role.value}")
    return user


@app.delete("/users/{user_id}", status_code=status.HTTP_204_NO_CONTENT, tags=["User Management (Admin)"])
def delete_user(
    user_id: int,
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin),
):
    user = db.get(User, user_id)
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    user.is_active = False
    db.commit()

    log_activity(db, admin.id, "DEACTIVATE_USER", f"User {user_id} deactivated")


# --- Projects Routes ---
def _project_or_404(db: Session, project_id: int):
    project = db.get(Project, project_id)
    if not project or project.is_deleted:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found")
    return project


def _assert_can_view_project(db: Session, project: Project, user: User):
    if user.role == RoleEnum.ADMIN:
        return
    if project.created_by == user.id or is_member(db, project.id, user.id):
        return
    raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not a member of this project")


def _assert_can_manage_project(db: Session, project: Project, user: User):
    if user.role == RoleEnum.ADMIN:
        return
    if user.role == RoleEnum.MANAGER and (
        project.created_by == user.id or is_member(db, project.id, user.id)
    ):
        return
    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail="You do not have permission to manage this project",
    )


@app.post("/projects", response_model=ProjectOut, status_code=status.HTTP_201_CREATED, tags=["Projects"])
def create_new_project(
    project_in: ProjectCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin_or_manager),
):
    project = create_project(db, project_in, current_user)
    log_activity(db, current_user.id, "CREATE_PROJECT", f"Project '{project.name}' created")
    return project


@app.get("/projects", response_model=list[ProjectOut], tags=["Projects"])
def get_projects(
    skip: int = 0,
    limit: int = 100,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    base = select(Project).where(Project.is_deleted.is_(False))
    if current_user.role == RoleEnum.ADMIN:
        stmt = base
    else:
        member_project_ids = select(ProjectMember.project_id).where(ProjectMember.user_id == current_user.id)
        stmt = base.where(
            (Project.created_by == current_user.id) | (Project.id.in_(member_project_ids))
        )
    return list(db.scalars(stmt.offset(skip).limit(limit)))


@app.get("/projects/{project_id}", response_model=ProjectOut, tags=["Projects"])
def get_project_by_id(
    project_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    project = _project_or_404(db, project_id)
    _assert_can_view_project(db, project, current_user)
    return project


@app.put("/projects/{project_id}", response_model=ProjectOut, tags=["Projects"])
def update_existing_project(
    project_id: int,
    project_in: ProjectUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    project = _project_or_404(db, project_id)
    _assert_can_manage_project(db, project, current_user)

    data = project_in.model_dump(exclude_unset=True)
    for field, value in data.items():
        setattr(project, field, value)
    db.commit()
    db.refresh(project)

    log_activity(db, current_user.id, "UPDATE_PROJECT", f"Project {project_id} updated")
    return project


@app.delete("/projects/{project_id}", status_code=status.HTTP_204_NO_CONTENT, tags=["Projects"])
def delete_existing_project(
    project_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    project = _project_or_404(db, project_id)
    if current_user.role != RoleEnum.ADMIN:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Only Admins can delete projects")
    project.is_deleted = True
    db.commit()

    log_activity(db, current_user.id, "DELETE_PROJECT", f"Project {project_id} deleted")


@app.post("/projects/{project_id}/members", response_model=ProjectMemberOut, status_code=status.HTTP_201_CREATED, tags=["Projects"])
def add_project_member(
    project_id: int,
    payload: ProjectMemberAdd,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    project = _project_or_404(db, project_id)
    _assert_can_manage_project(db, project, current_user)

    user = db.get(User, payload.user_id)
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    if is_member(db, project_id, payload.user_id):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="User is already a member")

    member = ProjectMember(project_id=project_id, user_id=payload.user_id)
    db.add(member)
    db.commit()
    db.refresh(member)

    log_activity(db, current_user.id, "ADD_PROJECT_MEMBER", f"User {payload.user_id} added to project {project_id}")
    return member


@app.get("/projects/{project_id}/members", response_model=list[ProjectMemberOut], tags=["Projects"])
def get_project_members(
    project_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    project = _project_or_404(db, project_id)
    _assert_can_view_project(db, project, current_user)
    return list(db.scalars(select(ProjectMember).where(ProjectMember.project_id == project_id)))


# --- Tasks Routes ---
def _task_or_404(db: Session, task_id: int):
    task = db.get(Task, task_id)
    if not task or task.is_deleted:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Task not found")
    return task


def _assert_manager_owns_project_for_task(db: Session, project_id: int, user: User):
    if user.role == RoleEnum.ADMIN:
        return
    project = db.get(Project, project_id)
    if not project or project.is_deleted:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found")
    if user.role == RoleEnum.MANAGER and (
        project.created_by == user.id or is_member(db, project_id, user.id)
    ):
        return
    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail="You do not have permission to manage tasks in this project",
    )


@app.post("/tasks", response_model=TaskOut, status_code=status.HTTP_201_CREATED, tags=["Tasks"])
def create_new_task(
    task_in: TaskCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin_or_manager),
):
    _assert_manager_owns_project_for_task(db, task_in.project_id, current_user)

    if task_in.assigned_to is not None and not is_member(db, task_in.project_id, task_in.assigned_to):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Assignee must be a member of the project",
        )

    task = Task(**task_in.model_dump())
    db.add(task)
    db.commit()
    db.refresh(task)

    log_activity(db, current_user.id, "CREATE_TASK", f"Task '{task.title}' created in project {task.project_id}")
    return task


@app.get("/tasks", response_model=list[TaskOut], tags=["Tasks"])
def get_tasks(
    project_id: int | None = None,
    status_filter: StatusEnum | None = Query(default=None, alias="status"),
    priority: PriorityEnum | None = None,
    skip: int = 0,
    limit: int = 100,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    base = select(Task).where(Task.is_deleted.is_(False))

    if current_user.role == RoleEnum.ADMIN:
        stmt = base
    elif current_user.role == RoleEnum.MANAGER:
        member_project_ids = select(ProjectMember.project_id).where(ProjectMember.user_id == current_user.id)
        owned_project_ids = select(Project.id).where(Project.created_by == current_user.id)
        stmt = base.where(
            Task.project_id.in_(member_project_ids) | Task.project_id.in_(owned_project_ids)
        )
    else:  # MEMBER: only tasks assigned to them
        stmt = base.where(Task.assigned_to == current_user.id)

    if project_id is not None:
        stmt = stmt.where(Task.project_id == project_id)
    if status_filter is not None:
        stmt = stmt.where(Task.status == status_filter.value)
    if priority is not None:
        stmt = stmt.where(Task.priority == priority.value)

    return list(db.scalars(stmt.offset(skip).limit(limit)))


@app.get("/tasks/{task_id}", response_model=TaskOut, tags=["Tasks"])
def get_task_by_id(
    task_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    task = _task_or_404(db, task_id)

    # Check read access
    allowed = False
    if current_user.role == RoleEnum.ADMIN:
        allowed = True
    elif current_user.role == RoleEnum.MANAGER:
        project = db.get(Project, task.project_id)
        if project and (project.created_by == current_user.id or is_member(db, task.project_id, current_user.id)):
            allowed = True
    else:
        allowed = task.assigned_to == current_user.id

    if not allowed:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not permitted to view this task")
    return task


@app.put("/tasks/{task_id}", response_model=TaskOut, tags=["Tasks"])
def update_existing_task(
    task_id: int,
    task_in: TaskUpdateFull,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    task = _task_or_404(db, task_id)
    data = task_in.model_dump(exclude_unset=True)

    if current_user.role in (RoleEnum.ADMIN, RoleEnum.MANAGER):
        if current_user.role == RoleEnum.MANAGER:
            _assert_manager_owns_project_for_task(db, task.project_id, current_user)
        if data.get("assigned_to") is not None and not is_member(db, task.project_id, data["assigned_to"]):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Assignee must be a member of the project",
            )
        for field, value in data.items():
            setattr(task, field, value)
        db.commit()
        db.refresh(task)

        log_activity(db, current_user.id, "UPDATE_TASK", f"Task {task_id} updated")
        return task

    # MEMBER: status-only update on their own task
    if task.assigned_to != current_user.id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="You can only update your own tasks")
    disallowed = set(data) - {"status"}
    if disallowed:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Members may only update the task's status",
        )
    if "status" not in data:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="No status provided")

    task.status = data["status"]
    db.commit()
    db.refresh(task)

    log_activity(db, current_user.id, "UPDATE_TASK_STATUS", f"Task {task_id} status set to {data['status']}")
    return task


@app.delete("/tasks/{task_id}", status_code=status.HTTP_204_NO_CONTENT, tags=["Tasks"])
def delete_existing_task(
    task_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin_or_manager),
):
    task = _task_or_404(db, task_id)
    _assert_manager_owns_project_for_task(db, task.project_id, current_user)
    task.is_deleted = True
    db.commit()

    log_activity(db, current_user.id, "DELETE_TASK", f"Task {task_id} deleted")
