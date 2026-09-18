import { useCallback, useEffect, useState } from "react";
import { api } from "../api/client";

type Hall = {
  id: number;
  name: string;
  rows: number;
  cols: number;
  aisle_cols: number[];
  current_version: number | null;
  current_version_frozen: boolean;
};

type Version = {
  id: number;
  hall_id: number;
  version: number;
  rows: number;
  cols: number;
  aisle_cols: number[];
  frozen: boolean;
  bound_showtimes: number;
};

export default function HallsPage() {
  const [halls, setHalls] = useState<Hall[]>([]);
  const [sel, setSel] = useState<number | null>(null);
  const [versions, setVersions] = useState<Version[]>([]);
  const [rows, setRows] = useState("");
  const [cols, setCols] = useState("");
  const [aisles, setAisles] = useState("");
  const [msg, setMsg] = useState("");
  const [err, setErr] = useState("");

  const reloadHalls = useCallback(async () => {
    const hs = await api<Hall[]>("/halls");
    setHalls(hs);
    return hs;
  }, []);

  useEffect(() => {
    reloadHalls().then((hs) => {
      if (hs.length) setSel((cur) => cur ?? hs[0].id);
    });
  }, [reloadHalls]);

  useEffect(() => {
    setMsg("");
    setErr("");
  }, [sel]);

  useEffect(() => {
    if (sel === null) return;
    const h = halls.find((x) => x.id === sel);
    if (!h) return;
    api<Version[]>(`/halls/${sel}/layout-versions`).then(setVersions);
    setRows(String(h.rows));
    setCols(String(h.cols));
    setAisles(h.aisle_cols.join(","));
  }, [sel, halls]);

  const latest = versions.length ? versions[versions.length - 1] : null;

  function parseForm() {
    const r = Number(rows);
    const c = Number(cols);
    if (!Number.isInteger(r) || r < 1 || !Number.isInteger(c) || c < 1) {
      throw new Error("行/列需为正整数");
    }
    const aisleNums = aisles
      .split(",")
      .map((s) => s.trim())
      .filter(Boolean)
      .map(Number);
    if (aisleNums.some((n) => !Number.isInteger(n))) {
      throw new Error("过道列需为逗号分隔的整数");
    }
    return { rows: r, cols: c, aisle_cols: aisleNums };
  }

  async function run(action: () => Promise<Version>, okText: (v: Version) => string) {
    setMsg("");
    setErr("");
    try {
      const v = await action();
      setMsg(okText(v));
      await reloadHalls();
    } catch (e) {
      setErr(e instanceof Error ? e.message : String(e));
    }
  }

  const saveCurrent = () => {
    if (!latest) return;
    run(
      () =>
        api<Version>(`/layout-versions/${latest.id}`, {
          method: "PUT",
          body: JSON.stringify(parseForm()),
        }),
      (v) => `已保存到 v${v.version}`
    );
  };

  const saveAsNew = () => {
    if (sel === null) return;
    run(
      () =>
        api<Version>(`/halls/${sel}/layout-versions`, {
          method: "POST",
          body: JSON.stringify(parseForm()),
        }),
      (v) => `已创建新版本 v${v.version}，后续场次可绑定使用`
    );
  };

  return (
    <>
      <h2>影厅 · 厅图版本</h2>
      <table className="table">
        <thead>
          <tr>
            <th>名称</th>
            <th>行×列</th>
            <th>过道列</th>
            <th>当前版本</th>
          </tr>
        </thead>
        <tbody>
          {halls.map((h) => (
            <tr
              key={h.id}
              onClick={() => setSel(h.id)}
              className={sel === h.id ? "row-sel" : ""}
              style={{ cursor: "pointer" }}
            >
              <td>{h.name}</td>
              <td className="mono">
                {h.rows} × {h.cols}
              </td>
              <td className="mono">{h.aisle_cols.join(", ") || "—"}</td>
              <td>
                {h.current_version !== null ? (
                  <span className={`badge ${h.current_version_frozen ? "badge-frozen" : "badge-open"}`}>
                    v{h.current_version} · {h.current_version_frozen ? "已冻结" : "可编辑"}
                  </span>
                ) : (
                  "—"
                )}
              </td>
            </tr>
          ))}
        </tbody>
      </table>

      {sel !== null && (
        <>
          <h3>版本列表</h3>
          <table className="table">
            <thead>
              <tr>
                <th>版本</th>
                <th>行×列</th>
                <th>过道列</th>
                <th>状态</th>
                <th>引用场次</th>
              </tr>
            </thead>
            <tbody>
              {versions.map((v) => (
                <tr key={v.id}>
                  <td className="mono">
                    v{v.version}
                    {latest?.id === v.id ? "（当前）" : ""}
                  </td>
                  <td className="mono">
                    {v.rows} × {v.cols}
                  </td>
                  <td className="mono">{v.aisle_cols.join(", ") || "—"}</td>
                  <td>
                    <span className={`badge ${v.frozen ? "badge-frozen" : "badge-open"}`}>
                      {v.frozen ? "已冻结" : "可编辑"}
                    </span>
                  </td>
                  <td className="mono">{v.bound_showtimes}</td>
                </tr>
              ))}
            </tbody>
          </table>

          <h3>编辑厅图{latest ? `（当前 v${latest.version}）` : ""}</h3>
          {latest?.frozen && (
            <div className="warn">
              当前版本已被场次引用且存在持有中持座，保存到当前版本将被拒绝；
              可修改后「另存为新版本」供后续场次选用，历史场次仍按原版本渲染。
            </div>
          )}
          <div className="toolbar">
            <label>
              行{" "}
              <input
                type="number"
                min={1}
                value={rows}
                onChange={(e) => setRows(e.target.value)}
                style={{ width: 72 }}
              />
            </label>
            <label>
              列{" "}
              <input
                type="number"
                min={1}
                value={cols}
                onChange={(e) => setCols(e.target.value)}
                style={{ width: 72 }}
              />
            </label>
            <label>
              过道列{" "}
              <input
                value={aisles}
                onChange={(e) => setAisles(e.target.value)}
                placeholder="如 5,6"
                style={{ width: 120 }}
              />
            </label>
            <button onClick={saveCurrent} disabled={!latest}>
              保存到当前版本
            </button>
            <button onClick={saveAsNew} className="btn-ghost">
              另存为新版本
            </button>
          </div>
          {msg && <div className="ok">{msg}</div>}
          {err && <div className="err">{err}</div>}
        </>
      )}
    </>
  );
}
