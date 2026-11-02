import datetime as dt
import math
import re
import requests
import streamlit as st
from zoneinfo import ZoneInfo

st.set_page_config(page_title='Predictor NFL + NBA | Kalshi', page_icon='🏈', layout='wide')
st.title('🏈🏀 Predictor NFL + NBA')
st.caption('Panel informativo en español • Datos deportivos de ESPN (fuente no oficial) • Mercado público de Kalshi')
st.warning('Las probabilidades son heurísticas experimentales, NO un modelo validado. No son garantías ni recomendaciones de apuestas. Nunca se colocan órdenes.')
BASE='https://site.api.espn.com/apis/site/v2/sports'
KALSHI='https://api.elections.kalshi.com/trade-api/v2'
TZ=ZoneInfo('America/New_York')

@st.cache_data(ttl=900, show_spinner=False)
def request_json(url, params=None):
    r=requests.get(url,params=params,timeout=18,headers={'User-Agent':'SportsDashboardExample/1.0'})
    r.raise_for_status()
    return r.json()

@st.cache_data(ttl=1800, show_spinner=False)
def historical_records(league, day):
    sport='basketball' if league=='NBA' else 'football'
    # Read daily final scores in a bounded window. Only actual FINAL games count.
    lookback=24 if league=='NBA' else 70
    games=[]
    for i in range(1,lookback+1):
        date=day-dt.timedelta(days=i)
        # NFL games cluster around Thu/Sun/Mon. Check each day for robust coverage.
        try:
            payload=request_json(f'{BASE}/{sport}/{league.lower()}/scoreboard',{'dates':date.strftime('%Y%m%d'),'limit':200})
            for event in payload.get('events',[]):
                comp=(event.get('competitions') or [{}])[0]
                status=event.get('status',{}).get('type',{})
                if not status.get('completed',False):
                    continue
                teams=comp.get('competitors',[])
                if len(teams)!=2:continue
                scores={t['team']['id']:float(t.get('score',0)) for t in teams if t.get('team',{}).get('id')}
                if len(scores)!=2:continue
                games.append((date,scores))
        except (requests.RequestException,ValueError,KeyError):
            continue
    return games

def score_strength(team_id, history, max_games=5):
    margins=[]
    for _,scores in history:
        if team_id in scores:
            opponent=next((v for k,v in scores.items() if k!=team_id),None)
            if opponent is not None:
                margins.append(scores[team_id]-opponent)
        if len(margins)>=max_games:break
    if not margins:return None,0
    return sum(margins)/len(margins),len(margins)

def estimate(home_id, away_id, league, history):
    hs,hn=score_strength(home_id,history)
    aw,an=score_strength(away_id,history)
    if hs is None or aw is None or min(hn,an)<3:return None,f'Datos insuficientes: {hn} y {an} partidos recientes'
    # Exploratory scoring heuristic: unvalidated logistic transform + modest home advantage.
    scale=13 if league=='NBA' else 10
    signal=((hs-aw)*0.45+ (2.0 if league=='NBA' else 1.5))/scale
    probability=1/(1+math.exp(-max(-2,min(2,signal))))
    probability=0.5+(probability-0.5)*0.65 # conservative shrinkage
    return probability, f'Últimos {hn} y {an} juegos; diferencial promedio de puntos {hs:+.1f} vs {aw:+.1f}'

def num_price(market):
    # Kalshi can expose fixed-point dollar string price fields or old cent fields.
    for key in ('yes_ask_dollars','yes_ask'):
        val=market.get(key)
        if val not in (None,''):
            try:
                x=float(val)
                if key=='yes_ask':x/=100
                if 0 <= x <=1:return x
            except (ValueError,TypeError):pass
    return None

league=st.radio('Liga', ['NBA','NFL'],horizontal=True)
day=st.date_input('Fecha del partido (hora de Nueva York)',value=dt.datetime.now(TZ).date())
sport='basketball' if league=='NBA' else 'football'
try:
    data=request_json(f'{BASE}/{sport}/{league.lower()}/scoreboard',{'dates':day.strftime('%Y%m%d'),'limit':200})
    events=data.get('events',[])
except (requests.RequestException,ValueError) as e:
    st.error(f'No fue posible obtener los partidos. Prueba más tarde. ({type(e).__name__})')
    st.stop()

if not events:st.info('No aparecen partidos para esta fecha. Prueba otro día.')
else:
    st.subheader(f'{len(events)} partidos encontrados')
    with st.spinner('Consultando historial reciente para estimaciones preliminares...'):
        history=historical_records(league,day)
    if not history:
        st.info('Sin historial reciente verificable. No se mostrarán porcentajes inventados.')
    for event in events:
        comp=(event.get('competitions') or [{}])[0]
        teams=comp.get('competitors',[])
        if len(teams)!=2:continue
        home=next((t for t in teams if t.get('homeAway')=='home'),None)
        away=next((t for t in teams if t.get('homeAway')=='away'),None)
        if not home or not away:continue
        h=home.get('team',{});a=away.get('team',{})
        hname=h.get('displayName','Local');aname=a.get('displayName','Visitante')
        status=event.get('status',{}).get('type',{})
        p,reason=estimate(h.get('id'),a.get('id'),league,history)
        with st.container(border=True):
            st.markdown(f'**{aname} @ {hname}**')
            st.caption(f"Fecha/hora: {event.get('date','—')} | Estado: {status.get('description','Desconocido')}")
            if status.get('completed') or status.get('state')=='in':
                st.write(f"Marcador: {aname} {away.get('score','—')} — {hname} {home.get('score','—')}")
            if status.get('state')=='pre':
                if p is None: st.info(reason)
                else:
                    c1,c2=st.columns(2)
                    c1.metric(f'Local: {hname}',f'{p:.1%}')
                    c2.metric(f'Visitante: {aname}',f'{1-p:.1%}')
                    st.caption('Estimación experimental con solo diferencial de puntos y localía; no contempla lesiones, titulares, descanso, cuotas ni validación histórica.')
                    st.caption(reason)
            else:st.caption('No se hace predicción retroactiva cuando el encuentro ya está en juego o finalizado.')

st.divider()
st.subheader('📈 Consultar precio en Kalshi (sin operar)')
st.write('Copia el código exacto **ticker** de un contrato de Kalshi. El programa no empareja partidos automáticamente: comprueba que el contrato sea el del equipo que estás evaluando.')
ticker=st.text_input('Ticker exacto del contrato',placeholder='Pega aquí el ticker del contrato')
if st.button('Consultar contrato'):
    ticker=ticker.strip().upper()
    if not re.fullmatch(r'[A-Z0-9_-]{3,160}',ticker):
        st.error('Introduce un ticker válido sin espacios.')
    else:
        try:
            market=request_json(f'{KALSHI}/markets/{ticker}')['market']
            st.write('**Contrato:**',market.get('title','—'))
            st.write('**Subtítulo/regla abreviada:**',market.get('subtitle','—'))
            st.write('**Estado:**',market.get('status','—'))
            price=num_price(market)
            if price is None:
                st.info('No se dispone de precio YES de compra utilizable. No se calculará comparación.')
            else:
                st.metric('Precio de compra YES',f'${price:.2f} por contrato')
                st.caption(f'Equivalente aproximado a {price:.1%} antes de comisiones. Este dato NO es una probabilidad calibrada ni una oportunidad garantizada.')
            st.info('La comparación de valor requiere vincular correctamente el resultado YES con un equipo, validar el modelo y descontar comisiones. Esta primera versión NO genera señales de compra.')
        except (requests.RequestException,KeyError,ValueError) as e:
            st.error(f'No se pudo consultar el mercado ({type(e).__name__}). Verifica el ticker.')

st.caption('Actualización: partidos e historial en caché 15/30 minutos. ESPN es una fuente no oficial y puede cambiar; Kalshi solo para datos públicos. Para automatización diaria real hace falta un programador externo o un servidor siempre activo.')
