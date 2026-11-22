import { api } from '../api.js';

export async function renderReview(el) {
  const [data, latest] = await Promise.all([
    api('/api/tickets'),
    api('/api/dashboard'),
  ]);
  const report = latest.latest_report;
  const landing = latest.entry_landing || {};
  el.innerHTML = `
    <div class="card">
      <h2>复核放行</h2>
      <div class="stat-strip">
        <div class="stat"><span class="muted">入舱标记</span><b>${landing.chip || '账册空'}</b></div>
        <div class="stat"><span class="muted">坏件余数</span><b class="${landing.bad_remainder ? 'hot' : ''}">${landing.bad_remainder ?? 0}</b></div>
        <div class="stat"><span class="muted">入舱落点</span><b>${landing.landing_count ?? 0}</b></div>
        <div class="stat"><span class="muted">清洗闸门</span><b class="${landing.gate_open ? 'okText' : 'badText'}">${landing.gate_open ? '开' : '闭'}</b></div>
      </div>
      ${report
        ? `<div class="hint-box">对账摘要：${report.summary}</div>`
        : '<div class="hint-box">尚无对账摘要，去「隔离对账」生成后再复核。</div>'}
      <table>
        <thead><tr><th>单号</th><th>条目</th><th>舱</th><th>裁决</th><th>操作</th></tr></thead>
        <tbody>
          ${(data.items || []).map((t) => `
            <tr>
              <td>${t.ticket_code}</td>
              <td>${t.item_key}</td>
              <td>${t.bin_code}</td>
              <td><span class="chip">${t.decision}</span></td>
              <td class="row">
                ${t.decision === '待决' ? `
                  <button data-d="放行" data-id="${t.id}">放行</button>
                  <button data-d="驳回回炉" data-id="${t.id}">驳回回炉</button>
                  <button data-d="废弃" data-id="${t.id}">废弃</button>
                ` : (t.comment || '')}
              </td>
            </tr>`).join('')}
        </tbody>
      </table>
    </div>`;
  el.querySelectorAll('button[data-d]').forEach((btn) => {
    btn.onclick = async () => {
      try {
        await api(`/api/tickets/${btn.dataset.id}/decide`, {
          method: 'POST',
          body: JSON.stringify({ decision: btn.dataset.d, comment: '台上裁决' }),
        });
      } catch (e) {
        alert(e.message);
      }
      await renderReview(el);
    };
  });
}
