from graphviz import Digraph

dot = Digraph("ERD", format="png")
dot.attr(rankdir="LR", fontname="Helvetica", bgcolor="white", splines="ortho")
dot.attr("node", shape="plaintext", fontname="Helvetica")

def esc(s):
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

def table(name, fields):
    rows = "".join(
        f'<TR><TD ALIGN="LEFT" PORT="{f.split()[0]}">{esc(f)}</TD></TR>' for f in fields
    )
    label = f'''<
<TABLE BORDER="1" CELLBORDER="0" CELLSPACING="0" CELLPADDING="6">
<TR><TD BGCOLOR="#2c3e50"><FONT COLOR="white"><B>{name}</B></FONT></TD></TR>
{rows}
</TABLE>>'''
    dot.node(name, label=label)

table("users", [
    "id (PK)",
    "full_name",
    "email (unique)",
    "password (hashed)",
    "role (admin/manager/member)",
    "is_active",
    "created_at",
])

table("projects", [
    "id (PK)",
    "name",
    "description",
    "created_by (FK -> users.id)",
    "created_at",
    "is_deleted",
])

table("project_members", [
    "id (PK)",
    "project_id (FK -> projects.id)",
    "user_id (FK -> users.id)",
    "added_at",
])

table("tasks", [
    "id (PK)",
    "title",
    "description",
    "status (Pending/In Progress/Completed)",
    "priority (Low/Medium/High)",
    "due_date",
    "assigned_to (FK -> users.id)",
    "project_id (FK -> projects.id)",
    "created_at",
    "is_deleted",
])

table("activity_logs", [
    "id (PK)",
    "user_id (FK -> users.id)",
    "action",
    "detail",
    "created_at",
])

dot.attr("edge", fontname="Helvetica", fontsize="10", color="#555555")
dot.edge("users", "projects", label="1 creates many", tailport="e", headport="w")
dot.edge("users", "project_members", label="1 has many", tailport="e", headport="w")
dot.edge("projects", "project_members", label="1 has many", tailport="e", headport="w")
dot.edge("projects", "tasks", label="1 has many", tailport="e", headport="w")
dot.edge("users", "tasks", label="1 assigned many", tailport="e", headport="w")
dot.edge("users", "activity_logs", label="1 has many", tailport="e", headport="w")

dot.render("/home/claude/pm-api/docs/schema_diagram", cleanup=True)
print("done")
