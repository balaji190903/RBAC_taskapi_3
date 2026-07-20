from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import ActivityLog, Project, ProjectMember, RoleEnum, Task, User
from app.schemas import ProjectCreate, ProjectUpdate, TaskCreate, UserCreate
from app.security import hash_password



def log_activity(db: Session, user_id: int | None, action: str, detail: str | None = None) -> None:
    entry = ActivityLog(user_id=user_id, action=action, detail=detail)
    db.add(entry)
    db.commit()


# --- User CRUD ---
def get_user(db: Session, user_id: int) -> User | None:
    return db.get(User, user_id)


def get_user_by_email(db: Session, email: str) -> User | None:
    return db.scalar(select(User).where(User.email == email))


def list_users(db: Session, skip: int = 0, limit: int = 100) -> list[User]:
    return list(db.scalars(select(User).offset(skip).limit(limit)))


def create_user(db: Session, user_in: UserCreate) -> User:
    user = User(
        full_name=user_in.full_name,
        email=user_in.email,
        password=hash_password(user_in.password),
        role=user_in.role,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def update_user_role(db: Session, user: User, role: RoleEnum) -> User:
    user.role = role
    db.commit()
    db.refresh(user)
    return user


def deactivate_user(db: Session, user: User) -> User:
    user.is_active = False
    db.commit()
    db.refresh(user)
    return user


# --- Project CRUD ---
def create_project(db: Session, project_in: ProjectCreate, creator: User) -> Project:
    project = Project(
        name=project_in.name,
        description=project_in.description,
        created_by=creator.id,
    )
    db.add(project)
    db.commit()
    db.refresh(project)
    # Creator is automatically a member of their own project.
    db.add(ProjectMember(project_id=project.id, user_id=creator.id))
    db.commit()
    return project


def get_project(db: Session, project_id: int) -> Project | None:
    project = db.get(Project, project_id)
    if project is None or project.is_deleted:
        return None
    return project


def is_member(db: Session, project_id: int, user_id: int) -> bool:
    return (
        db.scalar(
            select(ProjectMember).where(
                ProjectMember.project_id == project_id,
                ProjectMember.user_id == user_id,
            )
        )
        is not None
    )


def list_projects_for_user(db: Session, user: User, skip: int = 0, limit: int = 100) -> list[Project]:
    """Admin: all projects. Manager/Member: only projects they created or belong to."""
    base = select(Project).where(Project.is_deleted.is_(False))
    if user.role == RoleEnum.ADMIN:
        stmt = base
    else:
        member_project_ids = select(ProjectMember.project_id).where(ProjectMember.user_id == user.id)
        stmt = base.where(
            (Project.created_by == user.id) | (Project.id.in_(member_project_ids))
        )
    stmt = stmt.offset(skip).limit(limit)
    return list(db.scalars(stmt))


def update_project(db: Session, project: Project, project_in: ProjectUpdate) -> Project:
    data = project_in.model_dump(exclude_unset=True)
    for field, value in data.items():
        setattr(project, field, value)
    db.commit()
    db.refresh(project)
    return project


def soft_delete_project(db: Session, project: Project) -> None:
    project.is_deleted = True
    db.commit()


def add_member(db: Session, project_id: int, user_id: int) -> ProjectMember:
    member = ProjectMember(project_id=project_id, user_id=user_id)
    db.add(member)
    db.commit()
    db.refresh(member)
    return member


def list_members(db: Session, project_id: int) -> list[ProjectMember]:
    return list(db.scalars(select(ProjectMember).where(ProjectMember.project_id == project_id)))


# --- Task CRUD ---
def create_task(db: Session, task_in: TaskCreate) -> Task:
    task = Task(**task_in.model_dump())
    db.add(task)
    db.commit()
    db.refresh(task)
    return task


def get_task(db: Session, task_id: int) -> Task | None:
    task = db.get(Task, task_id)
    if task is None or task.is_deleted:
        return None
    return task


def list_tasks_for_user(
    db: Session,
    user: User,
    project_id: int | None = None,
    status: str | None = None,
    priority: str | None = None,
    skip: int = 0,
    limit: int = 100,
) -> list[Task]:
    base = select(Task).where(Task.is_deleted.is_(False))

    if user.role == RoleEnum.ADMIN:
        stmt = base
    elif user.role == RoleEnum.MANAGER:
        member_project_ids = select(ProjectMember.project_id).where(ProjectMember.user_id == user.id)
        owned_project_ids = select(Project.id).where(Project.created_by == user.id)
        stmt = base.where(
            Task.project_id.in_(member_project_ids) | Task.project_id.in_(owned_project_ids)
        )
    else:  # MEMBER: only tasks assigned to them
        stmt = base.where(Task.assigned_to == user.id)

    if project_id is not None:
        stmt = stmt.where(Task.project_id == project_id)
    if status is not None:
        stmt = stmt.where(Task.status == status)
    if priority is not None:
        stmt = stmt.where(Task.priority == priority)

    stmt = stmt.offset(skip).limit(limit)
    return list(db.scalars(stmt))


def update_task(db: Session, task: Task, data: dict) -> Task:
    for field, value in data.items():
        setattr(task, field, value)
    db.commit()
    db.refresh(task)
    return task


def soft_delete_task(db: Session, task: Task) -> None:
    task.is_deleted = True
    db.commit()


def user_can_access_task(db: Session, user: User, task: Task) -> bool:
    if user.role == RoleEnum.ADMIN:
        return True
    if user.role == RoleEnum.MANAGER:
        project = db.get(Project, task.project_id)
        return project is not None and (
            project.created_by == user.id or is_member(db, task.project_id, user.id)
        )
    return task.assigned_to == user.id
