/**
 * This file makes smaller copies of built text files for the web server.
 * walkFiles finds every file inside the build folder.
 * shouldCompress decides which file types benefit from extra compression.
 * writeCompressedCopies saves gzip and Brotli versions next to the original file.
 */

import { brotliCompressSync, constants, gzipSync } from "node:zlib";
import { fileURLToPath } from "node:url";
import { readdirSync, readFileSync, statSync, writeFileSync } from "node:fs";
import { join, extname } from "node:path";

const DIST_DIR = fileURLToPath(new URL("../dist/", import.meta.url));
const COMPRESSIBLE_EXTENSIONS = new Set([".css", ".html", ".js", ".json", ".svg", ".txt"]);

function walkFiles(directoryPath) {
  return readdirSync(directoryPath, { withFileTypes: true }).flatMap((entry) => {
    const fullPath = join(directoryPath, entry.name);
    if (entry.isDirectory()) {
      return walkFiles(fullPath);
    }
    return statSync(fullPath).isFile() ? [fullPath] : [];
  });
}

function shouldCompress(filePath) {
  return COMPRESSIBLE_EXTENSIONS.has(extname(filePath));
}

function writeCompressedCopies(filePath) {
  const fileBuffer = readFileSync(filePath);
  writeFileSync(`${filePath}.gz`, gzipSync(fileBuffer, { level: 9 }));
  writeFileSync(
    `${filePath}.br`,
    brotliCompressSync(fileBuffer, {
      params: { [constants.BROTLI_PARAM_QUALITY]: 11 },
    }),
  );
}

for (const filePath of walkFiles(DIST_DIR)) {
  if (shouldCompress(filePath)) {
    writeCompressedCopies(filePath);
  }
}
