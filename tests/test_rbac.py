from app.models import RoleEnum, User


def signup(client, email, password="Password123", name="Test User"):
    r = client.post(
        "/auth/signup",
        json={"full_name": name, "email": email, "password": password},
    )
    assert r.status_code == 201, r.text
    return r.json()


def login(client, email, password="Password123"):
    r = client.post("/auth/login", data={"username": email, "password": password})
    assert r.status_code == 200, r.text
    return r.json()["access_token"]


def test_login_accepts_json_body(client):
    signup(client, "jsonlogin@example.com", "Password123")
    r = client.post(
        "/auth/login",
        json={"username": "jsonlogin@example.com", "password": "Password123"},
    )
    assert r.status_code == 200, r.text
    assert "access_token" in r.json()


def auth_header(token):
    return {"Authorization": f"Bearer {token}"}


def promote_to_role(db_session, email, role: RoleEnum):
    user = db_session.query(User).filter(User.email == email).first()
    user.role = role
    db_session.commit()


def test_signup_forces_member_role(client):
    user = signup(client, "alice@example.com")
    assert user["role"] == "member"


def test_login_and_me(client):
    signup(client, "bob@example.com")
    token = login(client, "bob@example.com")
    r = client.get("/auth/me", headers=auth_header(token))
    assert r.status_code == 200
    assert r.json()["email"] == "bob@example.com"


def test_member_cannot_create_project(client):
    signup(client, "carol@example.com")
    token = login(client, "carol@example.com")
    r = client.post(
        "/projects",
        json={"name": "Should Fail", "description": "x"},
        headers=auth_header(token),
    )
    assert r.status_code == 403


def test_manager_can_create_project_and_admin_sees_it(client, db_session):
    signup(client, "manager1@example.com")
    promote_to_role(db_session, "manager1@example.com", RoleEnum.MANAGER)
    mgr_token = login(client, "manager1@example.com")

    r = client.post(
        "/projects",
        json={"name": "Website Revamp", "description": "Redesign the site"},
        headers=auth_header(mgr_token),
    )
    assert r.status_code == 201, r.text
    project = r.json()

    signup(client, "admin1@example.com")
    promote_to_role(db_session, "admin1@example.com", RoleEnum.ADMIN)
    admin_token = login(client, "admin1@example.com")

    r = client.get("/projects", headers=auth_header(admin_token))
    assert r.status_code == 200
    assert any(p["id"] == project["id"] for p in r.json())


def test_member_only_sees_assigned_task(client, db_session):
    # Manager creates a project and adds a member, then assigns them a task.
    signup(client, "manager2@example.com")
    promote_to_role(db_session, "manager2@example.com", RoleEnum.MANAGER)
    mgr_token = login(client, "manager2@example.com")

    member = signup(client, "dave@example.com")
    member_token = login(client, "dave@example.com")

    r = client.post(
        "/projects",
        json={"name": "Mobile App", "description": "Build the app"},
        headers=auth_header(mgr_token),
    )
    project_id = r.json()["id"]

    r = client.post(
        f"/projects/{project_id}/members",
        json={"user_id": member["id"]},
        headers=auth_header(mgr_token),
    )
    assert r.status_code == 201, r.text

    r = client.post(
        "/tasks",
        json={
            "title": "Design login screen",
            "project_id": project_id,
            "assigned_to": member["id"],
            "priority": "High",
        },
        headers=auth_header(mgr_token),
    )
    assert r.status_code == 201, r.text
    task = r.json()

    # Member sees only their own task
    r = client.get("/tasks", headers=auth_header(member_token))
    assert r.status_code == 200
    tasks = r.json()
    assert len(tasks) == 1
    assert tasks[0]["id"] == task["id"]

    # Member can update status
    r = client.put(
        f"/tasks/{task['id']}",
        json={"status": "In Progress"},
        headers=auth_header(member_token),
    )
    assert r.status_code == 200
    assert r.json()["status"] == "In Progress"

    # Member cannot reassign or change other fields
    r = client.put(
        f"/tasks/{task['id']}",
        json={"status": "Completed", "priority": "Low"},
        headers=auth_header(member_token),
    )
    assert r.status_code == 403


def test_only_admin_can_delete_project(client, db_session):
    signup(client, "manager3@example.com")
    promote_to_role(db_session, "manager3@example.com", RoleEnum.MANAGER)
    mgr_token = login(client, "manager3@example.com")

    r = client.post(
        "/projects",
        json={"name": "Temp Project", "description": "to delete"},
        headers=auth_header(mgr_token),
    )
    project_id = r.json()["id"]

    r = client.delete(f"/projects/{project_id}", headers=auth_header(mgr_token))
    assert r.status_code == 403

    signup(client, "admin2@example.com")
    promote_to_role(db_session, "admin2@example.com", RoleEnum.ADMIN)
    admin_token = login(client, "admin2@example.com")

    r = client.delete(f"/projects/{project_id}", headers=auth_header(admin_token))
    assert r.status_code == 204
