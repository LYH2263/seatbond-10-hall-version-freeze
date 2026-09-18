import { useCallback, useEffect, useState } from "react";
import { api } from "../api/client";

type Show = {
  id: number;
  hall_id: number;
  film_title: string;
  start_at: string;
  hall_name?: string;
  layout_version?: number | null;
  layout_frozen?: boolean;
};

type Hall = { id: number; name: string };
type Version = { id: number; version: number; frozen: boolean };

export default function ShowtimesPage() {
  const [rows, setRows] = useState<Show[]>([]);
  const [halls, setHalls] = useState<Hall[]>([]);
  const [versions, setVersions] = useState<Version[]>([]);
  const [film, setFilm] = useState("");
  const [hallId, setHallId] = useState<number | "">("");
  const [versionId, setVersionId] = useState<number | "">("");
  const [startAt, setStartAt] = useState("");
  const [msg, setMsg] = useState("");
  const [err, setErr] = useState("");

  const reload = useCallback(() => {
    api<Show[]>("/showtimes").then(setRows);
  }, []);

  useEffect(() => {
    reload();
    api<Hall[]>("/halls").then((hs) => {
      setHalls(hs);
      if (hs[0]) setHallId((cur) => (cur === "" ? hs[0].id : cur));
    });
  }, [reload]);

  useEffect(() => {
    if (hallId === "") return;
    api<Version[]>(`/halls/${hallId}/layout-versions`).then((vs) => {
      setVersions(vs);
      const latest = vs[vs.length - 1];
      setVersionId(latest ? latest.id : "");
    });
  }, [hallId]);

  async function submit() {
    setMsg("");
    setErr("");
    try {
      if (!film.trim()) throw new Error("请填写影片名");
      if (hallId === "") throw new Error("请选择影厅");
      if (!startAt) throw new Error("请选择开场时间");
      const body: Record<string, unknown> = {
        hall_id: hallId,
        film_title: film.trim(),
        start_at: startAt,
      };
      if (versionId !== "") body.layout_version_id = versionId;
      const st = await api<Show>("/showtimes", { method: "POST", body: JSON.stringify(body) });
      setMsg(`已创建场次：${st.film_title} · 绑定厅图 v${st.layout_version}`);
      setFilm("");
      setStartAt("");
      reload();
    } catch (e) {
      setErr(e instanceof Error ? e.message : String(e));
    }
  }

  return (
    <>
      <h2>场次</h2>
      <div className="toolbar">
        <input
          value={film}
          onChange={(e) => setFilm(e.target.value)}
          placeholder="影片名"
          style={{ width: 140 }}
        />
        <select value={hallId} onChange={(e) => setHallId(Number(e.target.value))}>
          {halls.map((h) => (
            <option key={h.id} value={h.id}>
              {h.name}
            </option>
          ))}
        </select>
        <select value={versionId} onChange={(e) => setVersionId(Number(e.target.value))}>
          {versions.map((v) => (
            <option key={v.id} value={v.id}>
              厅图 v{v.version}
              {v.frozen ? "（已冻结）" : ""}
            </option>
          ))}
        </select>
        <input
          type="datetime-local"
          value={startAt}
          onChange={(e) => setStartAt(e.target.value)}
        />
        <button onClick={submit}>创建场次</button>
      </div>
      {msg && <div className="ok">{msg}</div>}
      {err && <div className="err">{err}</div>}
      <table className="table">
        <thead>
          <tr>
            <th>影片</th>
            <th>影厅</th>
            <th>厅图版本</th>
            <th>开场</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((s) => (
            <tr key={s.id}>
              <td>{s.film_title}</td>
              <td>{s.hall_name}</td>
              <td>
                {s.layout_version != null ? (
                  <span className={`badge ${s.layout_frozen ? "badge-frozen" : "badge-open"}`}>
                    v{s.layout_version}
                    {s.layout_frozen ? " · 已冻结" : ""}
                  </span>
                ) : (
                  "—"
                )}
              </td>
              <td className="mono">{new Date(s.start_at).toLocaleString()}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </>
  );
}
