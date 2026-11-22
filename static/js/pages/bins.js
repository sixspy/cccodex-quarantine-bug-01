import { api } from '../api.js';

export async function renderBins(el) {
  const [bins, rows, overview] = await Promise.all([
    api('/api/bins'),
    api('/api/rows'),
    api('/api/enter_pack/overview'),
  ]);
  el.innerHTML = `
    <div class="card">
      <h2>隔离舱 · <span class="chip ${overview.chip === '已入舱' ? 'ok' : 'bad'}">入舱标记 ${overview.chip}</span></h2>
      <div class="stat-strip">
        <div class="stat"><span class="muted">入舱标记</span><b>${overview.chip}</b></div>
        <div class="stat"><span class="muted">坏件余数</span><b class="${overview.bad_remainder ? 'hot' : ''}">${overview.bad_remainder}</b></div>
        <div class="stat"><span class="muted">入舱落点</span><b>${overview.landing_count}</b></div>
        <div class="stat"><span class="muted">现行读引用</span><b>${overview.active_read}</b></div>
      </div>
      ${overview.gate_open ? '' : `<div class="hint-box bad">清洗闸门闭：${overview.gate_reasons.join('；')}</div>`}
      <table>
        <thead><tr><th>舱号</th><th>标题</th><th>状态</th><th>占用/容量</th><th>待复核</th><th>入舱落点</th><th>入舱标记</th></tr></thead>
        <tbody>
          ${(bins.items || []).map((b) => `
            <tr>
              <td>${b.bin_code}</td>
              <td>${b.title}</td>
              <td><span class="chip">${b.status}</span></td>
              <td>${b.row_count}/${b.capacity}</td>
              <td>${b.pending_count}</td>
              <td>${b.landing_count}</td>
              <td><span class="chip ${b.entry_mark === '已入舱' ? 'ok' : ''}">${b.entry_mark}</span></td>
            </tr>`).join('')}
        </tbody>
      </table>
    </div>
    <div class="card">
      <h2>舱内行 · 入舱落点</h2>
      <table>
        <thead><tr><th>舱</th><th>条目键</th><th>质量</th><th>原因</th><th>状态</th><th>落点指纹</th></tr></thead>
        <tbody>
          ${(rows.items || []).map((r) => `
            <tr>
              <td>${r.bin_code}</td>
              <td>${r.item_key}</td>
              <td>${r.quality}</td>
              <td>${r.reason}</td>
              <td><span class="chip">${r.status}</span></td>
              <td>${r.landing_id
                ? `<span class="chip ok" title="条目键+舱码指纹">${r.fingerprint}</span>`
                : '<span class="chip bad">无落点</span>'}</td>
            </tr>`).join('') || '<tr><td colspan="6" class="muted">暂无舱内行</td></tr>'}
        </tbody>
      </table>
    </div>
    <div class="card">
      <h2>近期入舱落点</h2>
      <table>
        <thead><tr><th>条目键</th><th>舱码</th><th>指纹</th><th>原因</th><th>时间</th></tr></thead>
        <tbody>
          ${(overview.landings || []).map((l) => `
            <tr>
              <td>${l.item_key}</td>
              <td>${l.bin_code}</td>
              <td><span class="chip ok">${l.fingerprint}</span></td>
              <td>${l.reason || ''}</td>
              <td>${l.created_at}</td>
            </tr>`).join('') || '<tr><td colspan="5" class="muted">暂无落点</td></tr>'}
        </tbody>
      </table>
    </div>`;
}
