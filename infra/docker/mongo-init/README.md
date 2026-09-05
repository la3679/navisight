# MongoDB container initialisation

`docker-compose.yml` mounts this directory read-only at
`/docker-entrypoint-initdb.d`. The `mongo` image runs every `.js` and `.sh` file
it finds there, in filename order, **once** — on the first start of a container
whose data volume is empty. It is not re-run afterwards, and never on an
existing volume.

**Nothing is here, deliberately.** NaviSight creates its own collections and
indexes from `app/db/indexes.py`, which runs before every import and is the
single declaration of what an index is for. A second place that also creates
indexes would be a second source of truth for the same thing.

This directory exists because the mount does. If you need a container-local user,
a role, or a fixture that must exist before the API ever connects, add it here.
The commit that adds one should say why it could not live in `indexes.py`.
