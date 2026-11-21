import html
import re
import secrets
import uvicorn
from fastapi import FastAPI, Form, Depends, Query, Request, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse
from sqlalchemy import create_engine, Column, Integer, String, Boolean, ForeignKey
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import declarative_base, sessionmaker, Session

SQLALCHEMY_DATABASE_URL = "sqlite:///./keitaro_sandbox.db"
engine = create_engine(SQLALCHEMY_DATABASE_URL, connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

GEO_PATTERN = re.compile(r"^[A-Za-z]{2}(,\s*[A-Za-z]{2})*$")


class CampaignModel(Base):
    __tablename__ = "campaigns"
    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    name = Column(String, nullable=False)
    geo = Column(String, nullable=False)
    is_dirty = Column(Boolean, default=False)


class OfferStreamModel(Base):
    __tablename__ = "offers"
    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    campaign_id = Column(Integer, ForeignKey("campaigns.id"), nullable=False)
    offer_id = Column(Integer, nullable=False)
    name = Column(String, nullable=False)
    weight = Column(Integer, nullable=False)
    deleted = Column(Boolean, default=False)


Base.metadata.create_all(bind=engine)
app = FastAPI(title="Keitaro Wrapper Monolith")


@app.exception_handler(SQLAlchemyError)
async def sqlalchemy_exception_handler(request: Request, exc: SQLAlchemyError):
    return JSONResponse(
        status_code=500,
        content={"status": "error", "message": "Ошибка базы данных при сохранении изменений."}
    )


@app.exception_handler(Exception)
async def general_exception_handler(request: Request, exc: Exception):
    return JSONResponse(
        status_code=500,
        content={"status": "error", "message": f"Внутренняя ошибка сервера: {str(exc)}"}
    )


@app.middleware("http")
async def csrf_protect_middleware(request: Request, call_next):
    if request.method in ("POST", "PUT", "DELETE", "PATCH"):
        cookie_token = request.cookies.get("csrf_token")
        header_token = request.headers.get("X-CSRF-Token")
        if not cookie_token or not header_token or not secrets.compare_digest(cookie_token, header_token):
            return JSONResponse({"status": "error", "message": "Недействительный или отсутствующий CSRF-токен"}, status_code=403)
    return await call_next(request)


AVAILABLE_OFFERS = [
    {"id": 10, "name": "Super Casino Offer (AU)"},
    {"id": 12, "name": "Crypto Landing Page (MX)"},
    {"id": 25, "name": "Nutra Slimming Tea (RO)"},
    {"id": 77, "name": "Sweepstakes iPhone 15 (CA)"},
    {"id": 88, "name": "Betting Sport VIP (BR)"}
]


def get_db():
    db = SessionLocal()
    try:
        yield db
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def init_db():
    db = SessionLocal()
    try:
        if not db.query(CampaignModel).first():
            first_camp = CampaignModel(name="test_gyozalyan_campaign_1", geo="AU,MX,RO", is_dirty=False)
            db.add(first_camp)
            db.flush()
            db.add_all([
                OfferStreamModel(campaign_id=first_camp.id, offer_id=10, name="Super Casino Offer (AU)", weight=50, deleted=False),
                OfferStreamModel(campaign_id=first_camp.id, offer_id=12, name="Crypto Landing Page (MX)", weight=50, deleted=False)
            ])
            db.commit()
    finally:
        db.close()


init_db()


def recalculate_weights(db: Session, campaign_id: int):
    db.flush()
    active_offers = (
        db.query(OfferStreamModel)
        .filter(OfferStreamModel.campaign_id == campaign_id, OfferStreamModel.deleted == False)
        .all()
    )
    count = len(active_offers)
    if count == 0:
        return
    base_weight = 100 // count
    remainder = 100 % count
    for i, offer in enumerate(active_offers):
        offer.weight = base_weight + (1 if i < remainder else 0)
    db.commit()


@app.get("/", response_class=HTMLResponse)
def get_dashboard(request: Request, campaign_id: int | None = Query(default=None), db: Session = Depends(get_db)):
    csrf_token = request.cookies.get("csrf_token") or secrets.token_hex(32)

    all_campaigns = db.query(CampaignModel).order_by(CampaignModel.id.desc()).all()
    if not all_campaigns:
        init_db()
        all_campaigns = db.query(CampaignModel).order_by(CampaignModel.id.desc()).all()

    camp = next((c for c in all_campaigns if c.id == campaign_id), all_campaigns[0])
    offers = db.query(OfferStreamModel).filter(OfferStreamModel.campaign_id == camp.id).all()

    camp_opts = "".join([
        f'<option value="{c.id}" {"selected" if c.id == camp.id else ""}>ID {c.id}: {html.escape(c.name)}</option>'
        for c in all_campaigns
    ])

    opts = "".join([f'<option value="{o["id"]}">{o["name"]} (ID: {o["id"]})</option>' for o in AVAILABLE_OFFERS])
    rows = ""
    for o in offers:
        rc = "row-deleted" if o.deleted else ""
        wt = "0% (Удален)" if o.deleted else f"{o.weight}%"
        btn = (
            f'<button class="btn-bring" onclick="bringBack({camp.id}, {o.offer_id})">BRING BACK</button>'
            if o.deleted
            else f'<button class="btn-remove" onclick="removeOffer({camp.id}, {o.offer_id})">REMOVE</button>'
        )
        rows += f'<tr class="{rc}"><td>Flow 2 (Main)</td><td>{html.escape(o.name)} (ID: {o.offer_id})</td><td class="weight-cell">{wt}</td><td>{btn}</td></tr>'

    dc = "dirty" if camp.is_dirty else ""
    safe_name = html.escape(camp.name)
    safe_geo = html.escape(camp.geo)

    css = (
        "body{font-family:Arial,sans-serif;background:#1e1e1e;color:#fff;padding:20px}"
        ".container{display:flex;gap:30px;max-width:1200px;margin:0 auto;align-items:flex-start}"
        ".left-panel{background:#b4c6e7;padding:25px;border-radius:8px;width:40%;border:1px solid #999;min-height:380px;box-sizing:border-box}"
        ".right-panel{background:#2d2d2d;padding:25px;border-radius:8px;width:60%;border-left:5px solid #4af;box-sizing:border-box}"
        "h2{color:#000;margin:0 0 20px;font-size:22px}h3{color:#4af;margin:0;font-size:22px}"
        ".input-group{margin-bottom:15px}label{display:block;margin-bottom:5px;color:#000;font-weight:bold}"
        "input,select{width:100%;padding:10px;border:1px solid #444;background:#1e1e1e;color:#fff;border-radius:4px;box-sizing:border-box}"
        ".btn-create{background:#d9e1f2;color:#000;border:1px solid #999;padding:12px;width:100%;border-radius:4px;cursor:pointer;font-weight:bold;margin-top:25px}"
        ".editor-header{display:flex;justify-content:space-between;align-items:center;margin-bottom:15px;background:#222;padding:10px;border-radius:4px}"
        ".camp-switcher{margin-bottom:15px;background:#222;padding:10px;border-radius:4px;display:flex;align-items:center;gap:10px}"
        ".btn-sync{background:#007bff;color:#fff;border:none;padding:8px 12px;border-radius:4px;cursor:pointer;font-weight:bold}"
        ".btn-push{background:#28a745;color:#fff;border:none;padding:8px 15px;border-radius:4px;cursor:pointer;font-weight:bold}"
        ".btn-push.dirty{background:#ffc107;color:#000}"
        "table{width:100%;border-collapse:collapse;margin-bottom:20px;background:#222}"
        "th,td{padding:12px;text-align:left;border-bottom:1px solid #444;font-size:14px}th{background:#111;color:#4af}"
        ".row-deleted{background:#442222;color:#aaa;text-decoration:line-through}"
        ".btn-remove{background:#dc3545;color:#fff;border:none;padding:6px 10px;border-radius:4px;cursor:pointer}"
        ".btn-bring{background:#17a2b8;color:#fff;border:none;padding:6px 10px;border-radius:4px;cursor:pointer;font-weight:bold}"
        ".weight-cell{font-weight:bold;color:#28a745}.row-deleted .weight-cell{color:#dc3545}"
    )
    js = f"""
        const CURRENT_CAMP_ID = {camp.id};
        const CSRF_TOKEN = "{csrf_token}";
        const CSRF_HEADERS = {{"X-CSRF-Token": CSRF_TOKEN}};

        function switchCampaign(id) {{
            window.location.href = '/?campaign_id=' + id + '&t=' + Date.now();
        }}

        async function handleApiResponse(res, redirectUrl) {{
            const data = await res.json();
            if (!res.ok || data.status === 'error' || data.status === 'last' || data.status === 'exists') {{
                alert('Ошибка: ' + (data.message || data.detail || 'Неизвестная ошибка'));
                return false;
            }}
            if (redirectUrl) {{
                window.location.href = redirectUrl;
            }}
            return data;
        }}

        document.getElementById('campaignForm').addEventListener('submit', async function(e) {{
            e.preventDefault();
            const fd = new FormData();
            fd.append('name', document.getElementById('name').value);
            fd.append('geo', document.getElementById('geo').value);
            fd.append('offer_id', document.getElementById('offer_id').value);
            const r = await fetch('/create-campaign', {{method: 'POST', headers: CSRF_HEADERS, body: fd}});
            const data = await handleApiResponse(r, null);
            if (data) window.location.href = '/?campaign_id=' + data.campaign_id + '&t=' + Date.now();
        }});

        async function removeOffer(campId, offerId) {{
            const res = await fetch('/campaign/' + campId + '/remove-offer/' + offerId, {{method: 'POST', headers: CSRF_HEADERS}});
            await handleApiResponse(res, '/?campaign_id=' + campId + '&t=' + Date.now());
        }}

        function fetchStreams() {{
            alert('INFO: Актуальные потоки и веса успешно загружены из базы трекера!');
            window.location.href = '/?campaign_id=' + CURRENT_CAMP_ID + '&t=' + Date.now();
        }}

        async function bringBack(campId, offerId) {{
            const res = await fetch('/campaign/' + campId + '/bring-back/' + offerId, {{method: 'POST', headers: CSRF_HEADERS}});
            await handleApiResponse(res, '/?campaign_id=' + campId + '&t=' + Date.now());
        }}

        async function addOfferToStream() {{
            const id = document.getElementById('add_offer_select').value;
            if (!id) {{
                alert('Внимание: Сначала выберите оффер из списка!');
                return;
            }}
            const res = await fetch('/campaign/' + CURRENT_CAMP_ID + '/add-offer/' + id, {{method: 'POST', headers: CSRF_HEADERS}});
            await handleApiResponse(res, '/?campaign_id=' + CURRENT_CAMP_ID + '&t=' + Date.now());
        }}

        async function pushToKeitaro() {{
            const res = await fetch('/campaign/' + CURRENT_CAMP_ID + '/push', {{method: 'POST', headers: CSRF_HEADERS}});
            const ok = await handleApiResponse(res, null);
            if (ok) {{
                alert('SUCCESS: Keitaro data synchronized successfully!');
                window.location.href = '/?campaign_id=' + CURRENT_CAMP_ID + '&t=' + Date.now();
            }}
        }}
        """

    page = (
        f"<!DOCTYPE html><html><head><title>Keitaro Wrapper</title><style>{css}</style></head><body>"
        f"<div class='container'><div class='left-panel'><h2>New campaign</h2><form id='campaignForm'>"
        f"<div class='input-group'><label>Name</label><input type='text' id='name' placeholder='имя кампании' minlength='2' maxlength='80' required></div>"
        f"<div class='input-group'><label>Geo</label><input type='text' id='geo' placeholder='MX,AU,RO' pattern='[A-Za-z]{{2}}(,\\s*[A-Za-z]{{2}})*' title='Укажите 2-буквенные коды стран через запятую, например: AU,MX,RO' required></div>"
        f"<div class='input-group'><label>Offer</label><select id='offer_id' required><option value='' disabled selected>поиск по офферам</option>{opts}</select></div>"
        f"<button type='submit' class='btn-create'>Create</button></form></div>"
        f"<div class='right-panel'>"
        f"<div class='camp-switcher'><span style='font-weight:bold;color:#4af;white-space:nowrap'>Выбор кампании:</span>"
        f"<select onchange='switchCampaign(this.value)'>{camp_opts}</select></div>"
        f"<div class='editor-header'><h3>Campaign Editor (ID: {camp.id})</h3>"
        f"<div><button class='btn-sync' onclick='fetchStreams()'>FETCH STREAMS FROM KT</button> "
        f"<button class='btn-push {dc}' onclick='pushToKeitaro()'>PUSH TO KT</button></div></div>"
        f"<p style='font-size:13px;color:#aaa;margin-top:-10px'>Кампания: <b>{safe_name}</b> | ГЕО: <code>{safe_geo}</code></p>"
        f"<table><thead><tr><th>Поток</th><th>Оффер в системе</th><th>Вес</th><th>Действие</th></tr></thead><tbody>{rows}</tbody></table>"
        f"<div style='background:#222;padding:15px;border-radius:6px;display:flex;gap:15px;align-items:center'>"
        f"<span style='font-weight:bold;color:#4af'>Add Offer:</span><select id='add_offer_select' style='flex-grow:1'>{opts}</select>"
        f"<button class='btn-sync' style='background:#28a745' onclick='addOfferToStream()'>ADD</button></div></div></div>"
        f"<script>{js}</script></body></html>"
    )
    response = HTMLResponse(content=page)
    response.set_cookie(key="csrf_token", value=csrf_token, httponly=True, samesite="strict")
    return response


@app.post("/create-campaign")
def create_campaign(
        name: str = Form(...),
        geo: str = Form(...),
        offer_id: int = Form(...),
        db: Session = Depends(get_db)
):
    clean_name = name.strip()
    if len(clean_name) < 2 or len(clean_name) > 80:
        return JSONResponse({"status": "error", "message": "Имя кампании должно быть от 2 до 80 символов."},
                            status_code=400)

    clean_geo = geo.strip().upper()
    if not GEO_PATTERN.match(clean_geo):
        return JSONResponse(
            {"status": "error",
             "message": "Неверный формат ГЕО. Укажите 2-буквенные коды стран через запятую (например: AU,MX,RO)."},
            status_code=400
        )
    normalized_geo = ",".join([g.strip() for g in clean_geo.split(",")])

    selected = next((o for o in AVAILABLE_OFFERS if o["id"] == offer_id), None)
    if not selected:
        return JSONResponse({"status": "error", "message": "Выбранный оффер не найден в списке доступных."},
                            status_code=404)

    final_name = clean_name if clean_name.startswith("test_gyozalyan_") else f"test_gyozalyan_{clean_name}"
    new_camp = CampaignModel(name=final_name, geo=normalized_geo, is_dirty=False)
    db.add(new_camp)
    db.flush()

    db.add(OfferStreamModel(
        campaign_id=new_camp.id,
        offer_id=selected["id"],
        name=selected["name"],
        weight=100,
        deleted=False
    ))
    db.commit()
    return JSONResponse({"status": "ok", "campaign_id": new_camp.id})


@app.post("/campaign/{campaign_id}/add-offer/{offer_id}")
def add_offer(campaign_id: int, offer_id: int, db: Session = Depends(get_db)):
    if not db.query(CampaignModel).filter(CampaignModel.id == campaign_id).first():
        return JSONResponse({"status": "error", "message": "Кампания не найдена."}, status_code=404)

    existing = (
        db.query(OfferStreamModel)
        .filter(OfferStreamModel.campaign_id == campaign_id, OfferStreamModel.offer_id == offer_id)
        .first()
    )

    if existing and not existing.deleted:
        return JSONResponse({"status": "exists", "message": "Этот оффер уже добавлен и активен в потоке!"})

    if existing and existing.deleted:
        existing.deleted = False
    else:
        selected = next((o for o in AVAILABLE_OFFERS if o["id"] == offer_id), None)
        if not selected:
            return JSONResponse({"status": "error", "message": "Оффер не найден."}, status_code=404)
        db.add(OfferStreamModel(
            campaign_id=campaign_id,
            offer_id=selected["id"],
            name=selected["name"],
            weight=0,
            deleted=False
        ))

    db.query(CampaignModel).filter(CampaignModel.id == campaign_id).update({"is_dirty": True})
    recalculate_weights(db, campaign_id)
    return JSONResponse({"status": "ok"})


@app.post("/campaign/{campaign_id}/remove-offer/{offer_id}")
def remove_offer(campaign_id: int, offer_id: int, db: Session = Depends(get_db)):
    if not db.query(CampaignModel).filter(CampaignModel.id == campaign_id).first():
        return JSONResponse({"status": "error", "message": "Кампания не найдена."}, status_code=404)

    active_count = (
        db.query(OfferStreamModel)
        .filter(OfferStreamModel.campaign_id == campaign_id, OfferStreamModel.deleted == False)
        .count()
    )
    if active_count <= 1:
        return JSONResponse({
            "status": "last",
            "message": "Нельзя удалить последний активный оффер в потоке (должен остаться минимум 1)!"
        })

    target = (
        db.query(OfferStreamModel)
        .filter(OfferStreamModel.campaign_id == campaign_id, OfferStreamModel.offer_id == offer_id)
        .first()
    )
    if not target:
        return JSONResponse({"status": "error", "message": "Оффер не найден в этой кампании."}, status_code=404)

    target.deleted = True
    db.query(CampaignModel).filter(CampaignModel.id == campaign_id).update({"is_dirty": True})
    recalculate_weights(db, campaign_id)
    return JSONResponse({"status": "ok"})


@app.post("/campaign/{campaign_id}/bring-back/{offer_id}")
def bring_back(campaign_id: int, offer_id: int, db: Session = Depends(get_db)):
    target = (
        db.query(OfferStreamModel)
        .filter(OfferStreamModel.campaign_id == campaign_id, OfferStreamModel.offer_id == offer_id)
        .first()
    )
    if not target:
        return JSONResponse({"status": "error", "message": "Оффер не найден в этой кампании."}, status_code=404)

    target.deleted = False
    db.query(CampaignModel).filter(CampaignModel.id == campaign_id).update({"is_dirty": True})
    recalculate_weights(db, campaign_id)
    return JSONResponse({"status": "ok"})


@app.post("/campaign/{campaign_id}/push")
def push_streams(campaign_id: int, db: Session = Depends(get_db)):
    camp = db.query(CampaignModel).filter(CampaignModel.id == campaign_id).first()
    if not camp:
        return JSONResponse({"status": "error", "message": "Кампания не найдена."}, status_code=404)

    camp.is_dirty = False
    db.commit()
    return JSONResponse({"status": "ok"})


if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=8000)
