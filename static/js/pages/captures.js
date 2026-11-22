import { api } from '../api.js';

export function landingBadge(item) {
  if (item.landing_id) {
    return `<span class="chip ok" title="入舱落点已钉定">落点 ${item.landing_bin_code || ''} · ${item.fingerprint || ''}</span>`;
  }
  if (item.status === '入舱') {
    return '<span class="chip bad" title="有入舱标记却无落点行">漂件·无落点</span>';
  }
  if (item.quality !== '合格') {
    return '<span class="chip bad">坏件余数</span>';
  }
  return '<span class="chip">—</span>';
}

export async function renderCaptures(el) {
  const [data, bins, overview] = await Promise.all([
    api('/api/batches'),
    api('/api/bins'),
    api('/api/enter_pack/overview'),
  ]);
  const openBin = (bins.items || []).find((b) => b.status === '开放');
  el.innerHTML = `
    <div class="card">
      <h2><span class="chip ${overview.chip === '已入舱' ? 'ok' : 'bad'}">入舱标记 ${overview.chip}</span> 抓取批次</h2>
      <div class="stat-strip">
        <div class="stat"><span class="muted">入舱标记</span><b>${overview.chip}</b></div>
        <div class="stat"><span class="muted">坏件余数</span><b class="${overview.bad_remainder ? 'hot' : ''}">${overview.bad_remainder}</b></div>
        <div class="stat"><span class="muted">入舱落点</span><b>${overview.landing_count}</b></div>
        <div class="stat"><span class="muted">清洗闸门</span><b class="${overview.gate_open ? 'okText' : 'badText'}">${overview.gate_open ? '开' : '闭'}</b></div>
      </div>
      ${overview.gate_reasons.length ? `<div class="hint-box bad">编排被挡：${overview.gate_reasons.join('；')}</div>` : ''}
      <div class="row">
        <input id="src" placeholder="来源名" />
        <input id="note" placeholder="备注" />
        <button id="create">新建批次</button>
      </div>
    </div>
    <div class="card">
      <table>
        <thead><tr><th>批号</th><th>来源</th><th>状态</th><th>条目</th><th>坏件余数</th><th>操作</th></tr></thead>
        <tbody>
          ${(data.items || []).map((b) => `
            <tr>
              <td>${b.batch_code}</td>
              <td>${b.source_name}</td>
              <td><span class="chip">${b.status}</span></td>
              <td>${b.item_count}</td>
              <td><span class="chip ${b.bad_count ? 'bad' : 'ok'}">${b.bad_count}</span></td>
              <td class="row">
                <button data-open="${b.id}">详情</button>
                <button data-close="${b.id}">关闭</button>
                ${openBin ? `<button data-auto="${b.id}">坏件入舱</button>` : ''}
              </td>
            </tr>`).join('')}
        </tbody>
      </table>
      <div id="detail" class="grid" style="margin-top:12px"></div>
    </div>`;
  el.querySelector('#create').onclick = async () => {
    await api('/api/batches', {
      method: 'POST',
      body: JSON.stringify({
        source_name: el.querySelector('#src').value,
        note: el.querySelector('#note').value,
      }),
    });
    await renderCaptures(el);
  };
  el.querySelectorAll('[data-close]').forEach((btn) => {
    btn.onclick = async () => {
      await api(`/api/batches/${btn.dataset.close}/close`, { method: 'POST', body: '{}' });
      await renderCaptures(el);
    };
  });
  el.querySelectorAll('[data-auto]').forEach((btn) => {
    btn.onclick = async () => {
      if (!openBin) return;
      try {
        await api('/api/quarantine/auto-enter', {
          method: 'POST',
          body: JSON.stringify({ batch_id: Number(btn.dataset.auto), bin_id: openBin.id }),
        });
      } catch (e) {
        alert(e.message);
      }
      await renderCaptures(el);
    };
  });
  el.querySelectorAll('[data-open]').forEach((btn) => {
    btn.onclick = async () => {
      const d = await api(`/api/batches/${btn.dataset.open}`);
      const box = el.querySelector('#detail');
      box.innerHTML = `
        <h3>${d.batch_code} 条目 · 坏件余数 <span class="chip ${d.bad_count ? 'bad' : 'ok'}">${d.bad_count}</span></h3>
        <div class="row">
          <input id="ikey" placeholder="条目键" />
          <select id="iq">
            <option>合格</option><option>缺字段</option><option>编码空</option><option>重复键</option>
          </select>
          <button id="addItem">追加条目</button>
        </div>
        <table>
          <thead><tr><th>键</th><th>质量</th><th>状态</th><th>入舱标记</th><th>入舱落点</th><th>操作</th></tr></thead>
          <tbody>
            ${(d.items || []).map((i) => `
              <tr>
                <td>${i.item_key}</td>
                <td><span class="chip ${i.quality === '合格' ? 'ok' : 'bad'}">${i.quality}</span></td>
                <td>${i.status}</td>
                <td>${i.landing_id ? '<span class="chip ok">已入舱</span>' : (i.status === '入舱' ? '<span class="chip bad">标记无落点</span>' : '<span class="chip">未入舱</span>')}</td>
                <td>${landingBadge(i)}</td>
                <td>${!i.landing_id && i.quality !== '合格' && i.status === '待检' && openBin
                  ? `<button data-enter="${i.id}">入舱落点</button>` : ''}</td>
              </tr>`).join('')}
          </tbody>
        </table>`;
      const enterButtons = box.querySelectorAll('[data-enter]');
      enterButtons.forEach((eb) => {
        eb.onclick = async () => {
          if (!openBin) return;
          try {
            await api('/api/quarantine/enter', {
              method: 'POST',
              body: JSON.stringify({ item_id: Number(eb.dataset.enter), bin_id: openBin.id, reason: '抓取侧手工入舱' }),
            });
          } catch (e) {
            alert(e.message);
          }
          btn.click();
        };
      });
      box.querySelector('#addItem').onclick = async () => {
        await api(`/api/batches/${d.id}/items`, {
          method: 'POST',
          body: JSON.stringify({
            item_key: box.querySelector('#ikey').value,
            quality: box.querySelector('#iq').value,
            payload: '{}',
          }),
        });
        btn.click();
      };
    };
  });
}
