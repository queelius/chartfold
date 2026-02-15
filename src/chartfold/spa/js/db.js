const DB = {
  instance: null,

  async init() {
    const status = document.querySelector('#loading p');
    status.textContent = 'Decoding database...';

    // Decode WASM binary from base64
    const wasmB64 = document.getElementById('sqljs-wasm').textContent;
    const wasmBinary = Uint8Array.from(atob(wasmB64), c => c.charCodeAt(0));

    // Initialize sql.js with inline WASM
    status.textContent = 'Initializing SQL engine...';
    const SQL = await initSqlJs({ wasmBinary: wasmBinary.buffer });

    // Decode and decompress the database
    status.textContent = 'Decompressing database...';
    const dbB64 = document.getElementById('chartfold-db').textContent;
    const dbCompressed = Uint8Array.from(atob(dbB64), c => c.charCodeAt(0));
    const dbBytes = await this.decompress(dbCompressed);

    this.instance = new SQL.Database(dbBytes);
    status.textContent = 'Ready';
  },

  async decompress(compressed) {
    const ds = new DecompressionStream('gzip');
    const writer = ds.writable.getWriter();
    writer.write(compressed);
    writer.close();
    const reader = ds.readable.getReader();
    const chunks = [];
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      chunks.push(value);
    }
    let len = 0;
    for (const c of chunks) len += c.length;
    const result = new Uint8Array(len);
    let off = 0;
    for (const c of chunks) { result.set(c, off); off += c.length; }
    return result;
  },

  query(sql, params = []) {
    const stmt = this.instance.prepare(sql);
    if (params.length) stmt.bind(params);
    const rows = [];
    while (stmt.step()) {
      rows.push(stmt.getAsObject());
    }
    stmt.free();
    return rows;
  },

  queryOne(sql, params = []) {
    const rows = this.query(sql, params);
    return rows.length > 0 ? rows[0] : null;
  },

  exec(sql) {
    return this.instance.exec(sql);
  }
};
