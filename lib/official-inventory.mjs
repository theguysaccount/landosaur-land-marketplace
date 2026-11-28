import { readFile } from "node:fs/promises";
import { join } from "node:path";

let inventory;

async function readSnapshot() {
  try {
    return await readFile(join(process.cwd(), "data", "official-inventory.json"), "utf8");
  } catch (error) {
    if (error.code !== "ENOENT") throw error;
    return readFile(join(process.cwd(), "dist", "data", "map.json"), "utf8");
  }
}

export function loadOfficialInventory() {
  if (!inventory) {
    inventory = readSnapshot()
      .then((raw) => {
        const { rows } = JSON.parse(raw);
        if (!Array.isArray(rows)) throw new Error("Invalid official inventory");
        return rows;
      })
      .catch((error) => {
        inventory = undefined;
        throw error;
      });
  }
  return inventory;
}
