# Project Management API with Role-Based Access Control (RBAC)

A FastAPI backend for managing projects, tasks, and project membership, with
three enforced roles: **Admin**, **Manager**, and **Member**.

Built with FastAPI, SQLAlchemy ORM, Pydantic, JWT authentication, and Alembic
migrations. Ships with SQLite by default (zero config) and is production-ready
for PostgreSQL via a single environment variable.

---

## Table of Contents
- [Architecture](#architecture)
- [Database Schema](#database-schema)
- [Roles & Permissions Matrix](#roles--permissions-matrix)
- [Getting Started](#getting-started)
  - [Option A: Local (venv)](#option-a-local-venv)
  - [Option B: Docker](#option-b-docker)
- [Authentication Flow](#authentication-flow)
- [API Reference](#api-reference)
- [Alembic Migrations](#alembic-migrations)
- [Testing](#testing)
- [Postman Collection](#postman-collection)
- [Design Decisions & Notes](#design-decisions--notes)
- [Bonus Features Implemented](#bonus-features-implemented)

---

## Architecture

```
app/
├── main.py                # FastAPI app instance, exception handlers
├── core/
│   ├── config.py          # Pydantic Settings (env vars)
│   └── security.py        # Password hashing, JWT create/decode
├── db/
│   ├── base_class.py       # SQLAlchemy declarative Base
│   └── session.py          # Engine + session factory + get_db dependency
├── models/                 # SQLAlchemy ORM models (User, Project, ProjectMember, Task, ActivityLog)
├── schemas/                 # Pydantic request/response schemas
├── crud/                    # Database access functions (business logic layer)
├── api/
│   ├── deps.py             # get_current_user, require_roles(...) dependencies
│   ├── api.py              # Aggregates all routers
│   └── routes/
│       ├── auth.py         # signup, login, me
│       ├── users.py        # admin-only user management
│       ├── projects.py     # project CRUD + membership
│       └── tasks.py        # task CRUD + assignment
alembic/                     # DB migrations
scripts/
│   ├── create_admin.py     # Bootstrap the first Admin account
│   └── generate_erd.py     # Regenerates docs/schema_diagram.png
docs/
│   └── schema_diagram.png  # Database ER diagram
tests/                       # Pytest suite (RBAC scenarios)
postman_collection.json      # Importable Postman collection
docker-compose.yml / Dockerfile
```

**Layering**: routes → crud → models. Routes handle HTTP concerns and
authorization checks; `crud/` holds reusable data-access/business logic;
`models/` defines the schema. Pydantic `schemas/` are the request/response
contracts, kept separate from ORM models.

---

## Database Schema

![Database Schema Diagram](docs/schema_diagram.png)

- **users** — id, full_name, email (unique), password (hashed), role (admin/manager/member), is_active, created_at
- **projects** — id, name, description, created_by (FK → users.id), created_at, is_deleted (soft delete)
- **project_members** — id, project_id (FK), user_id (FK), added_at — the join table enabling many-to-many project membership, with a unique constraint on (project_id, user_id)
- **tasks** — id, title, description, status, priority, due_date, assigned_to (FK → users.id, nullable), project_id (FK), created_at, is_deleted (soft delete)
- **activity_logs** — id, user_id (FK, nullable), action, detail, created_at (bonus audit trail)

Relationships:
- One **user** creates many **projects** (`Project.created_by`)
- Many-to-many between **users** and **projects** via **project_members**
- One **project** has many **tasks**; one **user** may be assigned many **tasks**

---

## Roles & Permissions Matrix

| Action                              | Admin | Manager                          | Member                    |
|--------------------------------------|:-----:|:---------------------------------:|:---------------------------:|
| Create project                       | ✅    | ✅                                 | ❌                          |
| View all projects                    | ✅    | ❌ (only created/joined projects)  | ❌ (only joined projects)   |
| Update project                       | ✅ any| ✅ only if creator/member          | ❌                          |
| Delete project                       | ✅    | ❌                                 | ❌                          |
| Add/view project members             | ✅    | ✅ (their projects)                | View only, if a member      |
| Create / reassign / set deadline task| ✅    | ✅ (within their projects)         | ❌                          |
| View tasks                           | ✅ all| ✅ tasks in their projects         | ✅ only tasks assigned to them |
| Update task status                   | ✅    | ✅                                 | ✅ (own tasks, `status` field only) |
| Update other task fields              | ✅    | ✅ (their projects)                | ❌ (403 if attempted)       |
| Manage users (roles, deactivate)     | ✅    | ❌                                 | ❌                          |

**Enforcement mechanism**: a `require_roles(*roles)` FastAPI dependency
handles coarse-grained role gating (e.g. only Admin/Manager may hit
`POST /projects`). On top of that, route handlers apply **resource-level**
checks — e.g. a Manager can only update a project if they created it or are a
member of it; a Member's `PUT /tasks/{id}` payload is inspected and any field
other than `status` is rejected with `403`, even if the task belongs to them.

> **Note on signup**: `POST /auth/signup` always creates a `member` account,
> regardless of what `role` is submitted in the body. This prevents trivial
> privilege escalation. The very first Admin must be created via
> `scripts/create_admin.py` (see below); every Admin/Manager promotion after
> that goes through `PUT /users/{id}/role`, which only an Admin can call.

---

## Getting Started

### Option A: Local (venv)

Requires Python 3.11+.

```bash
python3 -m venv venv
source venv/bin/activate           # Windows: venv\Scripts\activate
pip install -r requirements.txt

cp .env.example .env               # defaults to SQLite, no further config needed

# Apply DB migrations
alembic upgrade head

# Create the first Admin account (reads FIRST_ADMIN_* from .env, or pass args)
python scripts/create_admin.py admin@example.com "Admin@12345" "Super Admin"

# Run the API
python scripts/run_server.py

# Or with auto-reload enabled explicitly:
RELOAD=1 python scripts/run_server.py
```

Visit **http://localhost:8000/docs** for interactive Swagger UI, or
**http://localhost:8000/redoc** for ReDoc.

### Option B: Docker

```bash
docker compose up --build
```

This starts a PostgreSQL container plus the API (which runs `alembic upgrade
head` automatically on boot). Then, in a separate terminal, bootstrap the
first Admin:

```bash
docker compose exec api python scripts/create_admin.py admin@example.com "Admin@12345" "Super Admin"
```

API available at **http://localhost:8000/docs**.

---

## Authentication Flow

1. `POST /auth/signup` — register (always as `member`)
2. `POST /auth/login` — OAuth2 password flow; body is `x-www-form-urlencoded`
   with `username` (= email) and `password`; returns a JWT `access_token`
3. Send `Authorization: Bearer <token>` on subsequent requests
4. `GET /auth/me` — returns the current authenticated user
5. An Admin can promote a member: `PUT /users/{id}/role` with `{"role": "manager"}`

In Swagger UI, click **Authorize**, paste the token (Swagger will prefix
`Bearer` automatically if you use the `OAuth2PasswordBearer` flow — otherwise
type `Bearer <token>` in the value field), and all protected endpoints become
callable directly from the docs page.

---

## API Reference

### Auth
| Method | Path            | Access        | Description                     |
|--------|-----------------|---------------|----------------------------------|
| POST   | `/auth/signup`  | Public        | Register (forced to `member`)   |
| POST   | `/auth/login`   | Public        | Get JWT access token             |
| GET    | `/auth/me`      | Authenticated | Current user profile             |

### Users (Admin only)
| Method | Path                | Description                    |
|--------|---------------------|---------------------------------|
| GET    | `/users`            | List all users                  |
| PUT    | `/users/{id}/role`  | Change a user's role             |
| DELETE | `/users/{id}`       | Deactivate a user (soft delete)  |

### Projects
| Method | Path                        | Access                          |
|--------|-----------------------------|-----------------------------------|
| POST   | `/projects`                 | Admin, Manager                    |
| GET    | `/projects`                 | Authenticated (scoped by role)     |
| GET    | `/projects/{id}`            | Members of the project, or Admin  |
| PUT    | `/projects/{id}`            | Admin (any), Manager (own)         |
| DELETE | `/projects/{id}`            | Admin only                         |
| POST   | `/projects/{id}/members`    | Admin, Manager (own project)       |
| GET    | `/projects/{id}/members`    | Members of the project, or Admin  |

### Tasks
| Method | Path            | Access                                         |
|--------|-----------------|--------------------------------------------------|
| POST   | `/tasks`        | Admin, Manager (within their own project)         |
| GET    | `/tasks`        | Authenticated (scoped: all / own-projects / own-tasks); supports `?project_id=&status=&priority=&skip=&limit=` |
| GET    | `/tasks/{id}`   | Admin, Manager (own project), Member (if assigned) |
| PUT    | `/tasks/{id}`   | Admin/Manager: any field. Member: `status` only, own tasks. |
| DELETE | `/tasks/{id}`   | Admin, Manager (own project)                       |

Full interactive schema always available at `/docs` (Swagger) and `/redoc`,
and as raw JSON at `/openapi.json`.

---

## Alembic Migrations

```bash
# Create a new migration after changing models
alembic revision --autogenerate -m "describe your change"

# Apply migrations
alembic upgrade head

# Roll back one revision
alembic downgrade -1
```

`alembic/env.py` reads `DATABASE_URL` from the same `.env`/settings used by
the app, so migrations always target the same database as the running API.

---

## Testing

```bash
pytest -v
```

The suite (`tests/test_rbac.py`) uses an isolated SQLite test database and
covers:
- Signup always forces the `member` role
- Login + `/auth/me`
- A Member is blocked (403) from creating a project
- A Manager can create a project; an Admin can see it in `GET /projects`
- A Member sees only tasks assigned to them, can update `status`, but is
  rejected (403) when trying to change other fields
- Only an Admin can delete a project (Manager gets 403)

All 6 tests pass:
```
6 passed in 5.67s
```

---

## Postman Collection

Import [`postman_collection.json`](postman_collection.json) into Postman. It
includes requests for every endpoint, organized into Auth / Users / Projects
/ Tasks folders, with collection variables (`admin_token`, `manager_token`,
`member_token`, `project_id`, `task_id`) to chain requests together. Run the
login requests first (or set tokens manually) before the protected calls.

---

## Design Decisions & Notes

- **Soft deletes**: `Project` and `Task` use an `is_deleted` flag rather than
  hard deletes, so historical task/project data referenced by
  `activity_logs` or reporting isn't lost. Deleted records are excluded from
  all list/get queries.
- **Project creator is auto-added as a member**: when a project is created,
  the creator is inserted into `project_members` so ownership and membership
  checks compose cleanly (`created_by == user.id OR is_member(...)`).
- **Manager scope is data-driven, not global**: a Manager's ability to
  manage a project/task is always re-checked against `created_by` /
  `project_members`, not just their role name — this is what makes "assigned
  projects" and "assigned tasks" meaningful for Managers, rather than a
  blanket manager-can-touch-everything rule.
- **Member update restriction is enforced at the handler level**: the handler
  inspects exactly which fields were sent (`model_dump(exclude_unset=True)`)
  and rejects any field outside `{"status"}` for Members, since a plain
  request-body schema can't reliably express "this role gets a stricter
  subset of fields" on its own.
- **JWT** carries the user id (`sub`) and role as a claim; the role claim is
  informational only — every request re-reads the user's *current* role from
  the database, so revoking/changing a role takes effect immediately without
  needing to wait for token expiry.

---

## Bonus Features Implemented

- ✅ **Activity Logs** — every significant action (signup, login, project/task
  create/update/delete, membership changes, role changes) is recorded in
  `activity_logs` with the acting user, action name, and a detail string.
- ✅ **Soft Delete Support** — projects and tasks are soft-deleted (`is_deleted`)
  rather than removed from the database.
- ✅ **Pagination & Filtering** — `GET /projects` and `GET /users` support
  `skip`/`limit`; `GET /tasks` additionally supports `project_id`, `status`,
  and `priority` filters.
- ✅ **Docker Setup** — `Dockerfile` + `docker-compose.yml` (API + PostgreSQL,
  migrations run automatically on container start).
- ✅ **Unit Testing with Pytest** — see [Testing](#testing).

Not implemented (out of scope for this pass): email notifications, task
comments, file attachments.
