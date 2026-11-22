import { api } from '../api.js';

export async function renderReconcile(el) {
  const [data, overview] = await Promise.all([
    api('/api/reports'),
    api('/api/enter_pack/overview'),
  ]);
  const latest = (data.items || [])[0];
  el.innerHTML = `
    <div class="card">
      <h2>隔离对账</h2>
      <div class="stat-strip">
        <div class="stat"><span class="muted">入舱标记</span><b>${overview.chip}</b></div>
        <div class="stat"><span class="muted">坏件余数</span><b class="${overview.bad_remainder ? 'hot' : ''}">${overview.bad_remainder}</b></div>
        <div class="stat"><span class="muted">入舱落点</span><b>${overview.landing_count}</b></div>
        <div class="stat"><span class="muted">清洗闸门</span><b class="${overview.gate_open ? 'okText' : 'badText'}">${overview.gate_open ? '开' : '闭'}</b></div>
      </div>
      ${latest ? `<div class="hint-box">最新摘要：${latest.summary}</div>` : ''}
      <div class="row"><button id="run">生成对账报告</button></div>
      <table>
        <thead><tr><th>时间</th><th>摘要</th><th>待复核</th><th>放行</th><th>回炉</th><th>废弃</th><th>错位</th></tr></thead>
        <tbody>
          ${(data.items || []).map((r) => `
            <tr>
              <td>${r.created_at}</td>
              <td>${r.summary}</td>
              <td>${r.open_rows}</td>
              <td>${r.released}</td>
              <td>${r.reworking}</td>
              <td>${r.abandoned}</td>
              <td><span class="chip ${r.mismatch ? 'bad' : 'ok'}">${r.mismatch}</span></td>
            </tr>`).join('') || '<tr><td colspan="7" class="muted">暂无报告</td></tr>'}
        </tbody>
      </table>
    </div>`;
  el.querySelector('#run').onclick = async () => {
    await api('/api/reports/run', { method: 'POST', body: '{}' });
    await renderReconcile(el);
  };
}
