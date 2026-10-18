// Runs ONCE, on the first start of an empty MongoDB volume (docker-entrypoint-initdb.d).
// Creates the game's own database user with rights ONLY on the game database
// (the root user from MONGO_INITDB_ROOT_* is for maintenance, never used by the app).
const dbName = process.env.DB_NAME || 'ton_city';
const user = process.env.MONGO_APP_USER || 'gramcity';
const pwd = process.env.MONGO_APP_PASSWORD;
if (!pwd) { throw new Error('MONGO_APP_PASSWORD is not set'); }
db.getSiblingDB(dbName).createUser({ user, pwd, roles: [{ role: 'readWrite', db: dbName }] });
print(`created user ${user} on ${dbName}`);
