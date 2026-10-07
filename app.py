import os
import sqlite3
import secrets
import string
from datetime import datetime
from functools import wraps

from flask import (
    Flask,
    render_template,
    request,
    redirect,
    url_for,
    session,
    jsonify,
    flash
)
from werkzeug.security import generate_password_hash, check_password_hash


# =========================================================
# CONFIGURATION
# =========================================================

APP_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(APP_DIR, "slsu_connect.db")

app = Flask(__name__)

# Change this before deploying online
app.secret_key = os.environ.get(
    "SECRET_KEY",
    "change-this-secret-key"
)


# =========================================================
# DATABASE
# =========================================================

def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db():

    conn = get_db()

    conn.executescript("""

    CREATE TABLE IF NOT EXISTS users (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL,
        email TEXT NOT NULL UNIQUE,
        password_hash TEXT NOT NULL
    );

    CREATE TABLE IF NOT EXISTS schedules (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL,
        subject TEXT NOT NULL,
        day TEXT NOT NULL,
        time TEXT NOT NULL,

        FOREIGN KEY(user_id)
        REFERENCES users(id)
        ON DELETE CASCADE
    );

    CREATE TABLE IF NOT EXISTS deadlines (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL,
        title TEXT NOT NULL,
        duedate TEXT NOT NULL,

        FOREIGN KEY(user_id)
        REFERENCES users(id)
        ON DELETE CASCADE
    );

    CREATE TABLE IF NOT EXISTS reviewers (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL,
        subject TEXT NOT NULL,
        topic TEXT NOT NULL,
        notes TEXT NOT NULL,
        priority TEXT NOT NULL,

        FOREIGN KEY(user_id)
        REFERENCES users(id)
        ON DELETE CASCADE
    );

    CREATE TABLE IF NOT EXISTS groups (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        code TEXT NOT NULL UNIQUE,
        name TEXT NOT NULL,
        created_at TEXT NOT NULL
    );

    CREATE TABLE IF NOT EXISTS group_members (
        group_id INTEGER NOT NULL,
        user_id INTEGER NOT NULL,

        PRIMARY KEY(group_id, user_id),

        FOREIGN KEY(group_id)
        REFERENCES groups(id)
        ON DELETE CASCADE,

        FOREIGN KEY(user_id)
        REFERENCES users(id)
        ON DELETE CASCADE
    );

    CREATE TABLE IF NOT EXISTS group_tasks (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        group_id INTEGER NOT NULL,
        task TEXT NOT NULL,
        assignee TEXT NOT NULL,
        status TEXT NOT NULL DEFAULT 'Not Started',

        FOREIGN KEY(group_id)
        REFERENCES groups(id)
        ON DELETE CASCADE
    );

    CREATE TABLE IF NOT EXISTS group_logs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        group_id INTEGER NOT NULL,
        message TEXT NOT NULL,
        created_at TEXT NOT NULL,

        FOREIGN KEY(group_id)
        REFERENCES groups(id)
        ON DELETE CASCADE
    );

    """)

    conn.commit()
    conn.close()


# =========================================================
# USER FUNCTIONS
# =========================================================

def current_user():

    user_id = session.get("user_id")

    if not user_id:
        return None

    conn = get_db()

    user = conn.execute(
        "SELECT * FROM users WHERE id = ?",
        (user_id,)
    ).fetchone()

    conn.close()

    return user


def login_required(view):

    @wraps(view)
    def wrapped(*args, **kwargs):

        if not current_user():
            return redirect(url_for("index"))

        return view(*args, **kwargs)

    return wrapped


# =========================================================
# GROUP CODE
# =========================================================

def generate_group_code():

    alphabet = string.ascii_uppercase + string.digits

    conn = get_db()

    while True:

        code = "JGE-" + "".join(
            secrets.choice(alphabet)
            for _ in range(4)
        )

        exists = conn.execute(
            "SELECT id FROM groups WHERE code = ?",
            (code,)
        ).fetchone()

        if not exists:

            conn.close()

            return code


# =========================================================
# ACTIVITY LOG
# =========================================================

def log_group(conn, group_id, message):

    conn.execute(
        """
        INSERT INTO group_logs
        (group_id, message, created_at)
        VALUES (?, ?, ?)
        """,
        (
            group_id,
            message,
            datetime.now().isoformat(
                timespec="seconds"
            )
        )
    )


# =========================================================
# GROUP DATA
# =========================================================

def group_json(conn, group_id):

    group = conn.execute(
        """
        SELECT id, code, name
        FROM groups
        WHERE id = ?
        """,
        (group_id,)
    ).fetchone()

    if not group:
        return None

    members = conn.execute(
        """
        SELECT
            u.id,
            u.name,
            u.email

        FROM group_members gm

        JOIN users u
        ON u.id = gm.user_id

        WHERE gm.group_id = ?

        ORDER BY u.name
        """,
        (group_id,)
    ).fetchall()

    tasks = conn.execute(
        """
        SELECT
            id,
            task,
            assignee,
            status

        FROM group_tasks

        WHERE group_id = ?

        ORDER BY id DESC
        """,
        (group_id,)
    ).fetchall()

    logs = conn.execute(
        """
        SELECT message

        FROM group_logs

        WHERE group_id = ?

        ORDER BY id DESC

        LIMIT 50
        """,
        (group_id,)
    ).fetchall()

    return {

        "id": group["id"],

        "code": group["code"],

        "name": group["name"],

        "members": [
            dict(member)
            for member in members
        ],

        "tasks": [
            dict(task)
            for task in tasks
        ],

        "logs": [
            log["message"]
            for log in logs
        ]
    }


# =========================================================
# HOME PAGE
# =========================================================

@app.route("/")
def index():

    if current_user():

        return redirect(
            url_for("dashboard")
        )

    return render_template(
        "index.html",
        user=None
    )


# =========================================================
# SIGN UP
# =========================================================

@app.route(
    "/signup",
    methods=["POST"]
)
def signup():

    name = request.form.get(
        "name",
        ""
    ).strip()

    email = request.form.get(
        "email",
        ""
    ).strip().lower()

    password = request.form.get(
        "password",
        ""
    )

    if (
        not name
        or not email
        or len(password) < 6
    ):

        flash(
            "Please complete all fields. "
            "Password must be at least 6 characters.",
            "error"
        )

        return redirect(
            url_for("index")
        )

    conn = get_db()

    try:

        cur = conn.execute(
            """
            INSERT INTO users
            (name, email, password_hash)

            VALUES (?, ?, ?)
            """,
            (
                name,
                email,
                generate_password_hash(
                    password
                )
            )
        )

        conn.commit()

        session["user_id"] = cur.lastrowid

    except sqlite3.IntegrityError:

        flash(
            "Email already registered.",
            "error"
        )

        conn.close()

        return redirect(
            url_for("index")
        )

    conn.close()

    return redirect(
        url_for("dashboard")
    )


# =========================================================
# LOGIN
# =========================================================

@app.route(
    "/login",
    methods=["POST"]
)
def login():

    email = request.form.get(
        "email",
        ""
    ).strip().lower()

    password = request.form.get(
        "password",
        ""
    )

    conn = get_db()

    user = conn.execute(
        """
        SELECT *
        FROM users
        WHERE email = ?
        """,
        (email,)
    ).fetchone()

    conn.close()

    if (
        not user
        or not check_password_hash(
            user["password_hash"],
            password
        )
    ):

        flash(
            "Invalid login credentials.",
            "error"
        )

        return redirect(
            url_for("index")
        )

    session["user_id"] = user["id"]

    return redirect(
        url_for("dashboard")
    )


# =========================================================
# LOGOUT
# =========================================================

@app.route("/logout")
def logout():

    session.clear()

    return redirect(
        url_for("index")
    )


# =========================================================
# DASHBOARD
# =========================================================

@app.route("/dashboard")
@login_required
def dashboard():

    user = current_user()

    conn = get_db()

    schedules = conn.execute(
        """
        SELECT *
        FROM schedules
        WHERE user_id = ?

        ORDER BY id DESC
        """,
        (user["id"],)
    ).fetchall()

    deadlines = conn.execute(
        """
        SELECT *
        FROM deadlines
        WHERE user_id = ?

        ORDER BY duedate ASC
        """,
        (user["id"],)
    ).fetchall()

    reviewers = conn.execute(
        """
        SELECT *
        FROM reviewers
        WHERE user_id = ?

        ORDER BY id DESC
        """,
        (user["id"],)
    ).fetchall()

    groups = conn.execute(
        """
        SELECT
            g.id,
            g.code,
            g.name

        FROM groups g

        JOIN group_members gm
        ON gm.group_id = g.id

        WHERE gm.user_id = ?

        ORDER BY g.name
        """,
        (user["id"],)
    ).fetchall()

    conn.close()

    return render_template(
        "dashboard.html",

        user=user,

        schedules=schedules,

        deadlines=deadlines,

        reviewers=reviewers,

        groups=groups
    )


# =========================================================
# SCHEDULE
# =========================================================

@app.route(
    "/schedule/add",
    methods=["POST"]
)
@login_required
def add_schedule():

    user = current_user()

    conn = get_db()

    conn.execute(
        """
        INSERT INTO schedules
        (user_id, subject, day, time)

        VALUES (?, ?, ?, ?)
        """,
        (
            user["id"],

            request.form[
                "subject"
            ].strip(),

            request.form[
                "day"
            ].strip(),

            request.form[
                "time"
            ].strip()
        )
    )

    conn.commit()
    conn.close()

    return redirect(
        url_for("dashboard")
    )


@app.route(
    "/schedule/delete/<int:item_id>",
    methods=["POST"]
)
@login_required
def delete_schedule(item_id):

    conn = get_db()

    conn.execute(
        """
        DELETE FROM schedules

        WHERE id = ?
        AND user_id = ?
        """,
        (
            item_id,
            current_user()["id"]
        )
    )

    conn.commit()
    conn.close()

    return redirect(
        url_for("dashboard")
    )


# =========================================================
# DEADLINES
# =========================================================

@app.route(
    "/deadline/add",
    methods=["POST"]
)
@login_required
def add_deadline():

    user = current_user()

    conn = get_db()

    conn.execute(
        """
        INSERT INTO deadlines
        (user_id, title, duedate)

        VALUES (?, ?, ?)
        """,
        (
            user["id"],

            request.form[
                "title"
            ].strip(),

            request.form[
                "duedate"
            ]
        )
    )

    conn.commit()
    conn.close()

    return redirect(
        url_for("dashboard")
    )


@app.route(
    "/deadline/delete/<int:item_id>",
    methods=["POST"]
)
@login_required
def delete_deadline(item_id):

    conn = get_db()

    conn.execute(
        """
        DELETE FROM deadlines

        WHERE id = ?
        AND user_id = ?
        """,
        (
            item_id,
            current_user()["id"]
        )
    )

    conn.commit()
    conn.close()

    return redirect(
        url_for("dashboard")
    )


# =========================================================
# REVIEWER PAD
# =========================================================

@app.route(
    "/reviewer/add",
    methods=["POST"]
)
@login_required
def add_reviewer():

    user = current_user()

    conn = get_db()

    conn.execute(
        """
        INSERT INTO reviewers
        (
            user_id,
            subject,
            topic,
            notes,
            priority
        )

        VALUES (?, ?, ?, ?, ?)
        """,
        (
            user["id"],

            request.form[
                "subject"
            ].strip(),

            request.form[
                "topic"
            ].strip(),

            request.form[
                "notes"
            ].strip(),

            request.form[
                "priority"
            ]
        )
    )

    conn.commit()
    conn.close()

    return redirect(
        url_for("dashboard")
    )


@app.route(
    "/reviewer/delete/<int:item_id>",
    methods=["POST"]
)
@login_required
def delete_reviewer(item_id):

    conn = get_db()

    conn.execute(
        """
        DELETE FROM reviewers

        WHERE id = ?
        AND user_id = ?
        """,
        (
            item_id,
            current_user()["id"]
        )
    )

    conn.commit()
    conn.close()

    return redirect(
        url_for("dashboard")
    )


# =========================================================
# CREATE GROUP
# =========================================================

@app.route(
    "/group/create",
    methods=["POST"]
)
@login_required
def create_group():

    user = current_user()

    name = request.form.get(
        "name",
        ""
    ).strip()

    if not name:

        flash(
            "Group title is required.",
            "error"
        )

        return redirect(
            url_for("dashboard")
        )

    conn = get_db()

    code = generate_group_code()

    cur = conn.execute(
        """
        INSERT INTO groups
        (
            code,
            name,
            created_at
        )

        VALUES (?, ?, ?)
        """,
        (
            code,
            name,
            datetime.now().isoformat(
                timespec="seconds"
            )
        )
    )

    group_id = cur.lastrowid

    conn.execute(
        """
        INSERT INTO group_members
        (
            group_id,
            user_id
        )

        VALUES (?, ?)
        """,
        (
            group_id,
            user["id"]
        )
    )

    log_group(
        conn,
        group_id,
        f"Group created by {user['name']}"
    )

    conn.commit()
    conn.close()

    flash(
        f"Group created! Code: {code}",
        "success"
    )

    return redirect(
        url_for("dashboard")
    )


# =========================================================
# JOIN GROUP
# =========================================================

@app.route(
    "/group/join",
    methods=["POST"]
)
@login_required
def join_group():

    user = current_user()

    code = request.form.get(
        "code",
        ""
    ).strip().upper()

    conn = get_db()

    group = conn.execute(
        """
        SELECT *
        FROM groups

        WHERE code = ?
        """,
        (code,)
    ).fetchone()

    if not group:

        conn.close()

        flash(
            "Group code not found.",
            "error"
        )

        return redirect(
            url_for("dashboard")
        )

    existing = conn.execute(
        """
        SELECT 1

        FROM group_members

        WHERE group_id = ?
        AND user_id = ?
        """,
        (
            group["id"],
            user["id"]
        )
    ).fetchone()

    if not existing:

        conn.execute(
            """
            INSERT INTO group_members
            (
                group_id,
                user_id
            )

            VALUES (?, ?)
            """,
            (
                group["id"],
                user["id"]
            )
        )

        log_group(
            conn,
            group["id"],
            f"{user['name']} joined the online workspace."
        )

        conn.commit()

    conn.close()

    flash(
        f"Joined {group['name']} successfully.",
        "success"
    )

    return redirect(
        url_for("dashboard")
    )


# =========================================================
# LEAVE GROUP
# =========================================================

@app.route(
    "/group/<int:group_id>/leave",
    methods=["POST"]
)
@login_required
def leave_group(group_id):

    user = current_user()

    conn = get_db()

    conn.execute(
        """
        DELETE FROM group_members

        WHERE group_id = ?
        AND user_id = ?
        """,
        (
            group_id,
            user["id"]
        )
    )

    conn.commit()
    conn.close()

    return redirect(
        url_for("dashboard")
    )


# =========================================================
# CHECK GROUP MEMBERSHIP
# =========================================================

def get_member_group(
    conn,
    group_id
):

    user = current_user()

    return conn.execute(
        """
        SELECT g.*

        FROM groups g

        JOIN group_members gm
        ON gm.group_id = g.id

        WHERE g.id = ?
        AND gm.user_id = ?
        """,
        (
            group_id,
            user["id"]
        )
    ).fetchone()


# =========================================================
# GROUP API
# =========================================================

@app.route(
    "/api/group/<int:group_id>"
)
@login_required
def api_group(group_id):

    conn = get_db()

    group = get_member_group(
        conn,
        group_id
    )

    if not group:

        conn.close()

        return jsonify({
            "error":
            "Not a member of this group"
        }), 403

    data = group_json(
        conn,
        group_id
    )

    conn.close()

    return jsonify(data)


# =========================================================
# ADD GROUP TASK
# =========================================================

@app.route(
    "/group/<int:group_id>/task",
    methods=["POST"]
)
@login_required
def add_group_task(group_id):

    user = current_user()

    conn = get_db()

    group = get_member_group(
        conn,
        group_id
    )

    if not group:

        conn.close()

        return jsonify({
            "error":
            "Not a member"
        }), 403

    task = request.form.get(
        "task",
        ""
    ).strip()

    assignee = request.form.get(
        "assignee",
        ""
    ).strip()

    status = request.form.get(
        "status",
        "Not Started"
    )

    if not task or not assignee:

        conn.close()

        flash(
            "Task and assignee are required.",
            "error"
        )

        return redirect(
            url_for("dashboard")
        )

    conn.execute(
        """
        INSERT INTO group_tasks
        (
            group_id,
            task,
            assignee,
            status
        )

        VALUES (?, ?, ?, ?)
        """,
        (
            group_id,
            task,
            assignee,
            status
        )
    )

    log_group(
        conn,
        group_id,
        f'{user["name"]} added task "{task}" for {assignee}.'
    )

    conn.commit()
    conn.close()

    return redirect(
        url_for("dashboard")
    )


# =========================================================
# UPDATE GROUP TASK STATUS
# =========================================================

@app.route(
    "/group/<int:group_id>/task/<int:task_id>/status",
    methods=["POST"]
)
@login_required
def update_task_status(
    group_id,
    task_id
):

    user = current_user()

    new_status = request.form.get(
        "status",
        "Not Started"
    )

    conn = get_db()

    group = get_member_group(
        conn,
        group_id
    )

    if not group:

        conn.close()

        return jsonify({
            "error":
            "Not a member"
        }), 403

    task = conn.execute(
        """
        SELECT *

        FROM group_tasks

        WHERE id = ?
        AND group_id = ?
        """,
        (
            task_id,
            group_id
        )
    ).fetchone()

    if not task:

        conn.close()

        return jsonify({
            "error":
            "Task not found"
        }), 404

    conn.execute(
        """
        UPDATE group_tasks

        SET status = ?

        WHERE id = ?
        """,
        (
            new_status,
            task_id
        )
    )

    log_group(
        conn,
        group_id,
        f'{user["name"]} changed status of '
        f'"{task["task"]}" to {new_status}.'
    )

    conn.commit()
    conn.close()

    return redirect(
        url_for("dashboard")
    )


# =========================================================
# DELETE GROUP TASK
# =========================================================

@app.route(
    "/group/<int:group_id>/task/<int:task_id>/delete",
    methods=["POST"]
)
@login_required
def delete_group_task(
    group_id,
    task_id
):

    user = current_user()

    conn = get_db()

    group = get_member_group(
        conn,
        group_id
    )

    if not group:

        conn.close()

        return jsonify({
            "error":
            "Not a member"
        }), 403

    task = conn.execute(
        """
        SELECT *

        FROM group_tasks

        WHERE id = ?
        AND group_id = ?
        """,
        (
            task_id,
            group_id
        )
    ).fetchone()

    if task:

        conn.execute(
            """
            DELETE FROM group_tasks

            WHERE id = ?
            """,
            (task_id,)
        )

        log_group(
            conn,
            group_id,
            f'{user["name"]} deleted task '
            f'"{task["task"]}".'
        )

        conn.commit()

    conn.close()

    return redirect(
        url_for("dashboard")
    )


# =========================================================
# START APPLICATION
# =========================================================

if __name__ == "__main__":

    init_db()

    app.run(
        host="0.0.0.0",
        port=int(
            os.environ.get(
                "PORT",
                5000
            )
        ),
        debug=True
    )
