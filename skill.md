---
name: lepaix-flask-mongodb
description: >
  Project skill for the Lepaix Flask app using MongoDB Atlas and admin
  authentication. Use this skill for configuring Flask, managing `.env` secrets,
  setting up MongoDB Atlas, seeding admin credentials, fixing Blueprint auth,
  and extending the app structure for this project.
---

# Lepaix Flask + MongoDB Project Skill

This skill defines the design and implementation approach for the current
`Lepaix` project.

Key goals:

- Keep the Flask app modular and maintainable
- Keep secrets and connection strings in `.env`
- Use MongoDB Atlas securely via `MONGO_URI`
- Use `bcrypt` for admin password hashing and verification
- Organize routes with `Blueprint`

---

## Project structure

### Core files

- `run.py` — app entrypoint
- `config.py` — central Flask configuration
- `.env` — secret values and Atlas connection
- `app/__init__.py` — app factory and initialization
- `app/db.py` — MongoDB client setup and helpers
- `app/blueprints/` — route modules, including admin/auth
- `seed_admin.py` — admin seeding script

### App conventions

- Use `app.config.from_object('config.Config')` for configuration
- Avoid hardcoding secrets inside Python files
- Load `.env` before the app uses environment variables
- Keep `config.py` simple and declarative
- Use `Blueprint` for admin/auth routes and future expansion

---

## Environment and secrets

### `.env` structure

- `SECRET_KEY` — Flask session key
- `MONGO_URI` — full MongoDB Atlas URI
- `MONGO_DBNAME` — main database name
- `TEST_MONGO_URI` — optional test database URI
- `TEST_MONGO_DBNAME` — optional test database name
- `ADMIN_USERNAME` and `ADMIN_PASSWORD` — seed defaults only

### Secret handling rules

- never commit real credentials or password values
- prefer `os.environ.get("KEY")` over `os.environ["KEY"]` unless the value is mandatory
- keep the Atlas URI only in `.env`
- generate a strong `SECRET_KEY` and do not store it in source

---

## MongoDB Atlas and seeding

### Connection

- Use `MongoClient(app.config['MONGO_URI'])`
- `MONGO_URI` should be supplied only from `.env`
- `MONGO_DBNAME` selects the database used by the app

### Seed script

`seed_admin.py` should:

- load `.env` values into `os.environ`
- prompt for a password if one is not provided
- hash the password with `bcrypt`
- upsert the admin user record into the `admins` collection

---

## Admin auth design

### Login flow

- Query `get_db().admins.find_one({'username': username})`
- Validate with `bcrypt.check_password_hash(stored_hash, password)`
- Store `session['admin_id']` and `session['admin_username']` on success
- Return a generic error on failure

### Security notes

- `SECRET_KEY` is required for Flask sessions
- use HTTPS in production
- do not store plain text passwords
- keep session cookies secure and HTTP-only

---

## When to use this skill

Use this skill when the user asks about:

- Flask configuration and project setup
- MongoDB Atlas connection and `.env` handling
- admin auth, password hashing, and login flow
- Blueprint structure and application factory design
- seeding or migrating admin credentials

This skill should guide implementation decisions for the Lepaix project specifically.
