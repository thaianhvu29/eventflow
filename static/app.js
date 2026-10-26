'use strict';
const money = n => new Intl.NumberFormat('vi-VN').format(n) + 'đ';
const csrf = document.querySelector('meta[name="csrf-token"]').content;
async function post(url, data) {
  const response = await fetch(url, {method:'POST', headers:{'Content-Type':'application/json', 'X-CSRF-Token':csrf}, body:JSON.stringify(data)});
  let body;
  try { body = await response.json(); } catch { throw new Error('Không thể kết nối hệ thống. Vui lòng thử lại.'); }
  if (!response.ok) throw new Error(body.error || 'Yêu cầu chưa thành công.');
  return body;
}
function renderTicket(target, b) {
  target.replaceChildren();
  const card = document.createElement('div'); card.className='ticket';
  const add = (tag, value, className) => { const e=document.createElement(tag); e.textContent=value; if(className)e.className=className; card.append(e); };
  add('span','VÉ ĐIỆN TỬ · EVENTFLOW','eyebrow'); add('h3',b.event);
  add('p',b.date+' · '+b.time+' · '+b.venue+', '+b.city);
  add('strong',b.code,'ticket-code'); add('p',b.name+' · '+b.quantity+' vé · '+money(b.total));
  add('span',b.status,'ticket-status'); target.append(card);
}
const cards=[...document.querySelectorAll('.event-card')];
const search=document.querySelector('#search'); const city=document.querySelector('#city');
let category='Tất cả';
const normalize=s=>s.normalize('NFD').replace(/[\u0300-\u036f]/g,'').replace(/đ/g,'d').replace(/Đ/g,'D').toLowerCase();
function filterEvents() {
  let count=0;
  cards.forEach(card=>{ const show=(category==='Tất cả'||card.dataset.category===category)&&(!city.value||card.dataset.city===city.value)&&normalize(card.dataset.title+' '+card.dataset.category+' '+card.dataset.city).includes(normalize(search.value)); card.hidden=!show; if(show)count++; });
  document.querySelector('#event-count').textContent=count+' trải nghiệm để khám phá';
  document.querySelector('#empty-state').hidden=count!==0;
}
if(search) {
  search.addEventListener('input',filterEvents); city.addEventListener('change',filterEvents);
  document.querySelectorAll('.filter').forEach(button=>button.addEventListener('click',()=>{category=button.dataset.category; document.querySelectorAll('.filter').forEach(b=>{b.classList.toggle('selected',b===button); b.setAttribute('aria-pressed',String(b===button));}); filterEvents();}));
  document.querySelector('#reset-filters').addEventListener('click',()=>{search.value='';city.value='';document.querySelector('.filter').click();});
}
const booking=document.querySelector('#booking-form');
if(booking) {
  const quantity=document.querySelector('#quantity'); const error=document.querySelector('#booking-error');
  const update=()=>{document.querySelector('#total').textContent=money(Number(booking.dataset.price)*Number(quantity.value||0));};
  quantity.addEventListener('input',update);
  for(const [selector,delta] of [['#decrease',-1],['#increase',1]]) document.querySelector(selector).addEventListener('click',()=>{quantity.value=Math.max(1,Math.min(Number(quantity.max),Number(quantity.value||1)+delta));update();});
  booking.addEventListener('submit',async event=>{
    event.preventDefault(); const button=booking.querySelector('[type="submit"]'); button.disabled=true; button.textContent='Đang giữ chỗ…'; error.hidden=true;
    try {
      const b=await post('/api/bookings',{event_id:Number(booking.dataset.eventId),name:booking.elements.name.value.trim(),email:booking.elements.email.value.trim(),quantity:Number(quantity.value),request_key:booking.dataset.requestKey});
      renderTicket(document.querySelector('#booking-result'),b); document.querySelector('#success-dialog').showModal();
      button.textContent='Đã đặt vé thành công ✓';
    } catch(err) {error.textContent=err.message;error.hidden=false;button.disabled=false;button.textContent='Thử đặt vé lại ↗';}
  });
  const dialog=document.querySelector('#success-dialog');
  document.querySelector('.close-dialog').addEventListener('click',()=>{dialog.close();location.reload();});
  dialog.addEventListener('cancel',event=>{event.preventDefault();dialog.close();location.reload();});
}
const lookup=document.querySelector('#lookup-form');
if(lookup) lookup.addEventListener('submit',async event=>{
  event.preventDefault();const error=document.querySelector('#lookup-error'); const button=lookup.querySelector('button');error.hidden=true;button.disabled=true;button.textContent='Đang tìm vé…';document.querySelector('#ticket-result').replaceChildren();
  try {const b=await post('/api/tickets/lookup',{code:lookup.elements.code.value.trim(),email:lookup.elements.email.value.trim()});renderTicket(document.querySelector('#ticket-result'),b);} catch(err){error.textContent=err.message;error.hidden=false;}finally{button.disabled=false;button.textContent='Tìm vé của tôi ↗';}
});
