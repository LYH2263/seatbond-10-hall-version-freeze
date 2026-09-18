import { useEffect, useState } from "react";
import { api } from "../api/client";

type Hall = { id: number; name: string; rows: number; cols: number; aisle_cols: number[] };
type Version = {
  id: number;
  hall_id: number;
  version_no: number;
  rows: number;
  cols: number;
  aisle_cols: number[];
  frozen: boolean;
  showtime_count: number;
  created_at: string;
};

type Draft = { rows: string; cols: string; aisles: string };

function parseAisles(text: string): number[] {
  return text
    .split(/[,，\s]+/)
    .map((s) => s.trim())
    .filter(Boolean)
    .map(Number)
    .filter((n) => Number.isInteger(n));
}

export default function HallsPage() {
  const [halls, setHalls] = useState<Hall[]>([]);
  const [versions, setVersions] = useState<Record<number, Version[]>>({});
  const [editingId, setEditingId] = useState<number | null>(null);
  const [draft, setDraft] = useState<Draft>({ rows: "", cols: "", aisles: "" });
  const [msg, setMsg] = useState("");
  const [err, setErr] = useState("");

  async function load() {
    const hs = await api<Hall[]>("/halls");
    setHalls(hs);
    const entries = await Promise.all(
      hs.map(async (h) => [h.id, await api<Version[]>(`/halls/${h.id}/versions`)] as const)
    );
    setVersions(Object.fromEntries(entries));
  }

  useEffect(() => {
    load().catch((e) => setErr(e instanceof Error ? e.message : String(e)));
  }, []);

  function startEdit(v: Version) {
    setEditingId(v.id);
    setDraft({
      rows: String(v.rows),
      cols: String(v.cols),
      aisles: v.aisle_cols.join(","),
    });
    setMsg("");
    setErr("");
  }

  async function save(v: Version) {
    setMsg("");
    setErr("");
    try {
      await api<Version>(`/versions/${v.id}`, {
        method: "PUT",
        body: JSON.stringify({
          rows: Number(draft.rows),
          cols: Number(draft.cols),
          aisle_cols: parseAisles(draft.aisles),
        }),
      });
      setEditingId(null);
      setMsg(`影厅版本 v${v.version_no} 已保存`);
      await load();
    } catch (e) {
      // 冻结版本保存会 409 —— 服务端返回的可读提示直接展示
      setErr(e instanceof Error ? e.message : String(e));
    }
  }

  async function copyAsNew(h: Hall) {
    setMsg("");
    setErr("");
    try {
      const v = await api<Version>(`/halls/${h.id}/versions`, {
        method: "POST",
        body: JSON.stringify({}),
      });
      setMsg(`已复制为新版本 v${v.version_no}（未冻结，可编辑过道与行列，供后续场次绑定）`);
      await load();
    } catch (e) {
      setErr(e instanceof Error ? e.message : String(e));
    }
  }

  return (
    <>
      <h2>影厅 · 厅图版本</h2>
      {msg && <div className="ok">{msg}</div>}
      {err && <div className="err">{err}</div>}
      {halls.map((h) => (
        <section key={h.id} style={{ marginBottom: "1.5rem" }}>
          <div className="toolbar" style={{ marginBottom: ".4rem" }}>
            <strong>{h.name}</strong>
            <span className="mono">
              当前 {h.rows} × {h.cols} · 过道 {h.aisle_cols.join(", ") || "—"}
            </span>
            <button onClick={() => copyAsNew(h)}>复制为新版本</button>
          </div>
          <table className="table">
            <thead>
              <tr>
                <th>版本</th>
                <th>行×列</th>
                <th>过道列</th>
                <th>状态</th>
                <th>引用场次</th>
                <th>操作</th>
              </tr>
            </thead>
            <tbody>
              {(versions[h.id] || []).map((v) => (
                <tr key={v.id}>
                  <td className="mono">v{v.version_no}</td>
                  {editingId === v.id ? (
                    <>
                      <td>
                        <input
                          value={draft.rows}
                          onChange={(e) => setDraft({ ...draft, rows: e.target.value })}
                          style={{ width: 48 }}
                        />{" "}
                        ×{" "}
                        <input
                          value={draft.cols}
                          onChange={(e) => setDraft({ ...draft, cols: e.target.value })}
                          style={{ width: 48 }}
                        />
                      </td>
                      <td>
                        <input
                          value={draft.aisles}
                          onChange={(e) => setDraft({ ...draft, aisles: e.target.value })}
                          placeholder="如 5,6"
                          style={{ width: 96 }}
                        />
                      </td>
                    </>
                  ) : (
                    <>
                      <td className="mono">
                        {v.rows} × {v.cols}
                      </td>
                      <td className="mono">{v.aisle_cols.join(", ") || "—"}</td>
                    </>
                  )}
                  <td>
                    {v.frozen ? (
                      <span title="已有场次持座引用此版本，行列与过道不可再改；请复制为新版本">
                        🔒 冻结
                      </span>
                    ) : (
                      "可编辑"
                    )}
                  </td>
                  <td className="mono">{v.showtime_count}</td>
                  <td>
                    {editingId === v.id ? (
                      <>
                        <button onClick={() => save(v)}>保存</button>{" "}
                        <button onClick={() => setEditingId(null)}>取消</button>
                      </>
                    ) : (
                      <button onClick={() => startEdit(v)}>编辑</button>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          {(versions[h.id] || []).some((v) => v.frozen) && (
            <p className="mono" style={{ fontSize: ".78rem", opacity: 0.75 }}>
              🔒 冻结版本已被持座场次引用：行列与过道不可再改，保存将被拒绝；请「复制为新版本」后在新版本上调整，新场次即可绑定新版本。
            </p>
          )}
        </section>
      ))}
    </>
  );
}
