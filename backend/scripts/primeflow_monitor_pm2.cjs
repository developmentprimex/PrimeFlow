// Query the existing daemon. The PM2 CLI can launch one if none is running.
const path = require("node:path");
const root = process.argv[2];
const axon = require(path.join(root, "modules", "pm2-axon"));
const rpc = require(path.join(root, "modules", "pm2-axon-rpc"));
const socket = axon.socket("req");
const client = new rpc.Client(socket);
const names = new Set(["primex-backend", "backend-api-flow", "primex-public-api"]);

const deadline = setTimeout(() => process.exit(1), 5000);
socket.on("error", () => process.exit(1));
socket.once("connect", () => {
  client.call("getMonitorData", {}, (error, rows) => {
    if (error || !Array.isArray(rows)) process.exit(1);
    const processes = rows.filter((row) => names.has(row.name)).map((row) => ({
      name: row.name,
      pid: row.pid,
      status: row.pm2_env.status,
    }));
    clearTimeout(deadline);
    socket.close();
    process.stdout.write(JSON.stringify(processes));
  });
});
socket.connect("\\\\.\\pipe\\rpc.sock");
