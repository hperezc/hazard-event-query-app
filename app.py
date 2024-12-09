# -*- coding: utf-8 -*-
import dash
from dash import dcc, html, dash_table
from dash.dependencies import Input, Output, State
import dash_bootstrap_components as dbc
import geopandas as gpd
import pandas as pd
import plotly.express as px
from dash.exceptions import PreventUpdate
import plotly.graph_objects as go
from sqlalchemy import create_engine
import os
from dotenv import load_dotenv
import unicodedata
from sqlalchemy.exc import SQLAlchemyError
from functools import lru_cache
import numpy as np
import math
import socket

def is_port_in_use(port):
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        return s.connect_ex(('127.0.0.1', port)) == 0

# Configuración global para todos los gráficos
GRAPH_CONFIG = {
    'displayModeBar': True,
    'responsive': True,
    'displaylogo': False,
    'modeBarButtonsToRemove': ['lasso2d', 'select2d'],
    'toImageButtonOptions': {
        'format': 'png',
        'filename': 'grafico',
        'height': None,
        'width': None,
        'scale': 2
    }
}

# Configuración común para layouts
GRAPH_LAYOUT = {
    'margin': dict(l=50, r=50, t=50, b=50),
    'autosize': True,
    'height': 400,
    'hoverlabel': dict(
        bgcolor="white",
        font_size=12,
        font_family="Arial",
        bordercolor='gray',
        namelength=-1
    ),
    'font': dict(
        family="Arial",
        size=12
    ),
    'hovermode': 'closest'
}


# Agrega esta línea cerca del inicio de tu script, después de las importaciones
mapbox_access_token = 'pk.eyJ1IjoiaHBlcmV6Yzk3IiwiYSI6ImNtMm92ZWRzZTBrNTkybnBydGkydzJyajMifQ.ng34bPCD2cV5eNBnBMiCXg'

# Cargar variables de entorno
load_dotenv()

# Configuración de la conexión a PostgreSQL
DB_USER = os.getenv('DB_USER')
DB_PASSWORD = os.getenv('DB_PASSWORD')
DB_HOST = os.getenv('DB_HOST')
DB_PORT = os.getenv('DB_PORT', '5432')  # Agregamos el puerto
DB_NAME = os.getenv('DB_NAME')

# Crear conexión a la base de datos
DATABASE_URL = f"postgresql://{DB_USER}:{DB_PASSWORD}@{DB_HOST}:{DB_PORT}/{DB_NAME}"
engine = create_engine(
    DATABASE_URL,
    pool_size=5,
    max_overflow=10,
    pool_timeout=30,
    pool_recycle=1800,
    connect_args={
        'connect_timeout': 10,
        'application_name': 'TableroEventosAmenaza'
    }
)

# Verificar la conexión
with engine.connect() as conn:
    print("Conexión exitosa a la base de datos")

# Modificar la función cargar_datos
@lru_cache(maxsize=32)
def cargar_datos():
    try:
        # Cargar municipios
        query_municipios = """
        SELECT "MpNombre", ST_Transform(geometry, 4326) as geometry 
        FROM municipios
        """
        gdf_municipios = gpd.GeoDataFrame.from_postgis(
            query_municipios, 
            engine, 
            geom_col='geometry',
            crs='EPSG:4326'
        )

        # Cargar eventos desde la base UNGRD
        query_eventos = """
        SELECT "MUNICIPIO", 
               "TIPO", 
               "FECHA",
               "COMENTARIOS",
               'UNGRD' as "FUENTE"
        FROM eventos_ungrd
        """
        with engine.connect().execution_options(timeout=30) as conn:
            df_eventos_ungrd = pd.read_sql(query_eventos, conn)

        # Cargar eventos desde DAGRAN
        query_eventos_dagran = """
        SELECT "MUNICIPIO",
               "TIPO",
               "FECHA",
               "COMENTARIOS",
               'DAGRAN' as "FUENTE"
        FROM eventos_dagran
        """
        with engine.connect().execution_options(timeout=30) as conn:
            df_eventos_dagran = pd.read_sql(query_eventos_dagran, conn)

        # Cargar eventos desde SIMMA
        query_eventos_simma = """
        SELECT "TIPO",
               "SUBTIPO" as "COMENTARIOS",
               ST_Transform(geometry, 4326) as geometry,
               'SIMMA' as "FUENTE"
        FROM eventos_simma
        """
        gdf_eventos_shp = gpd.GeoDataFrame.from_postgis(
            query_eventos_simma,
            engine,
            geom_col='geometry',
            crs='EPSG:4326'
        )
        gdf_eventos_shp['FECHA'] = None

        # Combinar todos los eventos
        df_eventos_municipio = pd.concat([
            df_eventos_ungrd,
            df_eventos_dagran
        ], ignore_index=True)

        return gdf_municipios, df_eventos_municipio, gdf_eventos_shp

    except SQLAlchemyError as e:
        print(f"Error al cargar datos: {str(e)}")
        return gpd.GeoDataFrame(), pd.DataFrame(), gpd.GeoDataFrame()

# Modificar la carga inicial de datos
gdf_municipios, df_eventos_municipio, gdf_eventos_shp = cargar_datos()

# Ajusta el valor de tolerancia para la simplificación
# Un valor más pequeño preservará más detalles, un valor más grande simplificará más
# Prueba con diferentes valores hasta encontrar el equilibrio adecuado
gdf_municipios['geometry'] = gdf_municipios['geometry'].simplify(tolerance=0.003)

gdf_municipios = gdf_municipios[['MpNombre', 'geometry']]  # Mantén solo las columnas necesarias

# Modificar la función obtener_municipios_unicos
def obtener_municipios_unicos():
    try:
        query = """
        SELECT DISTINCT "MUNICIPIO" FROM (
            SELECT "MUNICIPIO" FROM eventos_ungrd
            UNION
            SELECT "MUNICIPIO" FROM eventos_dagran
        ) as municipios
        WHERE "MUNICIPIO" IS NOT NULL
        """
        with engine.connect().execution_options(timeout=10) as conn:
            municipios = pd.read_sql(query, conn)['MUNICIPIO'].unique()
        return sorted([mun.split('/')[1].strip() if '/' in mun else mun for mun in municipios])
    except SQLAlchemyError as e:
        print(f"Error al obtener municipios: {str(e)}")
        return []

municipios_unicos = obtener_municipios_unicos()

def normalizar_texto(texto):
    """
    Elimina tildes y convierte a mayúsculas
    """
    if pd.isna(texto):
        return texto
    texto_sin_tildes = ''.join(c for c in unicodedata.normalize('NFD', str(texto))
                              if unicodedata.category(c) != 'Mn')
    return texto_sin_tildes.upper().strip()

def normalizar_tipo_evento(tipo):
    """
    Normaliza los tipos de eventos para asegurar consistencia entre las tres fuentes de datos.
    """
    if pd.isna(tipo):
        return "NO ESPECIFICADO"
    
    tipo = str(tipo).upper().strip()
    
    normalizacion = {
        'MOVIMIENTO EN MASA': [
            'DESLIZAMIENTO', 'REMOCION EN MASA', 'DERRUMBE', 
            'MOVIMIENTOS EN MASA', 'DESLIZAMIENTOS', 'REPTACIÓN',
            'MOVIMIENTO', 'MASA'
        ],
        'INUNDACION': [
            'INUNDACIONES', 'DESBORDAMIENTO', 'ANEGACIÓN',
            'ENCHARCAMIENTO', 'INUNDACIÓN', 'DESBORDAMIENTOS'
        ],
        'AVENIDA TORRENCIAL': [
            'AVENIDA', 'TORRENCIAL', 'CRECIENTE', 
            'FLUJO TORRENCIAL', 'AVENIDAS TORRENCIALES',
            'FLUJOS', 'AVENIDAS'
        ],
        'VENDAVAL': [
            'VIENTOS FUERTES', 'TORMENTA', 'VENDAVALES',
            'TORNADO', 'TORMENTA ELÉCTRICA', 'VENDAVAL'
        ],
        'SISMO': [
            'TEMBLOR', 'TERREMOTO', 'ACTIVIDAD SÍSMICA',
            'SISMICIDAD', 'MICROSISMICIDAD'
        ],
        'INCENDIO FORESTAL': [
            'INCENDIO DE COBERTURA VEGETAL', 'INCENDIO COBERTURA',
            'QUEMA', 'CONFLAGRACIÓN', 'INCENDIOS'
        ],
        'SEQUIA': [
            'DESABASTECIMIENTO', 'SEQUÍA', 'DÉFICIT HÍDRICO',
            'SEQUIA', 'DESABASTECIMIENTO DE AGUA'
        ],
        'GRANIZADA': [
            'GRANIZO', 'PRECIPITACIÓN SÓLIDA', 'GRANIZADAS'
        ],
        'EROSION': [
            'SOCAVACIÓN', 'EROSIÓN COSTERA', 'EROSIÓN FLUVIAL',
            'EROSIÓN', 'SOCAVAMIENTO'
        ]
    }
    
    for categoria, variantes in normalizacion.items():
        if tipo in variantes or any(variante in tipo for variante in variantes):
            return categoria
    
    return tipo

# Modificar la función obtener_tipos_eventos
def obtener_tipos_eventos():
    try:
        query = """
        SELECT DISTINCT "TIPO" FROM (
            SELECT "TIPO" FROM eventos_ungrd
            UNION
            SELECT "TIPO" FROM eventos_dagran
            UNION
            SELECT "TIPO" FROM eventos_simma
        ) as tipos
        WHERE "TIPO" IS NOT NULL
        """
        with engine.connect().execution_options(timeout=10) as conn:
            tipos = pd.read_sql(query, conn)['TIPO'].unique()
        tipos_normalizados = [normalizar_tipo_evento(tipo) for tipo in tipos if pd.notna(tipo)]
        return sorted(list(set(tipos_normalizados)))
    except SQLAlchemyError as e:
        print(f"Error al obtener tipos de eventos: {str(e)}")
        return []

# Obtener los tipos de eventos después de definir las funciones
tipos_eventos = obtener_tipos_eventos()

# Inicializar la aplicación Dash con un tema de Bootstrap
app = dash.Dash(__name__, 
                external_stylesheets=[
                    dbc.themes.BOOTSTRAP,
                    'https://use.fontawesome.com/releases/v5.15.4/css/all.css'
                ])

# Estilos personalizados
SIDEBAR_STYLE = {
    "position": "fixed",
    "top": 0,
    "left": 0,
    "bottom": 0,
    "width": "16rem",
    "padding": "2rem 1rem",
    "background-color": "#f8f9fa",  # Color gris claro
    "border-right": "1px solid #dee2e6"  # Borde sutil
}

CONTENT_STYLE = {
    "margin-left": "18rem",
    "margin-right": "2rem",
    "padding": "2rem 1rem",
    "@media (max-width: 768px)": {
        "margin-left": "0",
        "margin-top": "6rem"
    }
}

# Definir una paleta de colores profesional
COLORS = {
    'primary': '#0d6efd',     # Azul principal
    'secondary': '#6c757d',   # Gris
    'success': '#198754',     # Verde
    'info': '#0dcaf0',        # Azul claro
    'dark': '#212529',        # Negro/gris oscuro
    'light': '#f8f9fa',       # Gris muy claro
    'white': '#ffffff',       # Blanco
    'border': '#dee2e6'       # Color para bordes
}

# Estilos para las tarjetas
CARD_STYLE = {
    'box-shadow': '0 2px 4px rgba(0,0,0,0.1)',
    'border': f'1px solid {COLORS["border"]}',
    'border-radius': '8px'
}

# Paleta de colores para gráficos
GRAPH_COLORS = [
    '#0d6efd',  # Azul principal
    '#198754',  # Verde
    '#dc3545',  # Rojo
    '#fd7e14',  # Naranja
    '#6f42c1',  # Morado
    '#20c997',  # Verde azulado
    '#0dcaf0',  # Azul claro
    '#ffc107'   # Amarillo
]

# Primero definimos las fuentes disponibles
FUENTES_DATOS = ['UNGRD', 'DAGRAN', 'SIMMA']


# Modificar el sidebar para incluir iconos
sidebar = html.Div([
    html.H4([
        html.I(className="fas fa-filter me-2"),  # Icono para Filtros
        "Filtros"
    ], className="mb-3 text-secondary d-flex align-items-center"),
    html.Hr(style={'border-color': COLORS['border']}),
    
    # Filtro de municipio con icono
    dbc.Row([
        dbc.Col([
            dbc.Label([
                html.I(className="fas fa-map-marker-alt me-2"),  # Icono para Municipio
                "Selecciona un municipio"
            ], html_for="municipio-input", className="mb-2 text-secondary fw-bold d-flex align-items-center"),
            dbc.Input(
                id="municipio-input",
                type="text",
                placeholder="Nombre del municipio",
                className="mb-3",
                style={'border-radius': '6px'}
            )
        ])
    ]),
    
    # Mejorar apariencia de las cards de filtros con iconos
    dbc.Card([
        dbc.CardHeader([
            html.I(className="fas fa-database me-2"),  # Icono para Fuentes de Datos
            "Fuentes de Datos"
        ], className="fw-bold d-flex align-items-center", style={'background-color': COLORS['light']}),
        dbc.CardBody(
            dcc.Checklist(
                id='fuentes-checklist',
                options=[{'label': f' {fuente}', 'value': fuente} for fuente in FUENTES_DATOS],
                value=FUENTES_DATOS,
                labelStyle={'display': 'block', 'margin-bottom': '8px'},
                className="checklist-custom"
            )
        )
    ], className="mb-3", style=CARD_STYLE),
    
    # Filtro de tipos de eventos con icono
    dbc.Card([
        dbc.CardHeader([
            html.I(className="fas fa-exclamation-triangle me-2"),  # Icono para Tipos de Eventos
            "Tipos de Eventos"
        ], className="fw-bold d-flex align-items-center", style={'background-color': COLORS['light']}),
        dbc.CardBody(
            dcc.Checklist(
                id='tipo-evento-checklist',
                options=[{'label': 'Seleccionar todos', 'value': 'todos'}] + 
                        [{'label': tipo, 'value': tipo} for tipo in tipos_eventos],
                value=[],
                labelStyle={'display': 'block', 'margin-bottom': '8px'},
                className="checklist-custom"
            )
        )
    ], style={"maxHeight": "400px", "overflowY": "scroll"}, className="mb-3")
], style=SIDEBAR_STYLE)

# Modificar el contenido principal para incluir la barra de título y el modal
content = html.Div([
    # Barra de título
    dbc.Navbar(
        dbc.Container([
            dbc.Row([
                dbc.Col(html.H3([
                    html.I(className="fas fa-database me-2"),  # Icono para el título
                    "Consulta y Análisis de Eventos de Amenaza para Colombia"
                ], className="text-white mb-0 d-flex align-items-center")),
                dbc.Col(
                    dbc.Button([
                        html.I(className="fas fa-info-circle me-2"),  # Icono para el botón
                        "Acerca de"
                    ], 
                    id="open-modal", 
                    color="light",
                    className="ms-auto",
                    style={'font-weight': '500'}),
                    width="auto"
                )
            ], align="center", className="w-100")
        ]),
        color="dark",
        dark=True,
        className="mb-4 shadow-sm"
    ),

    # Modal
    dbc.Modal([
        dbc.ModalHeader("Acerca de"),
        dbc.ModalBody([
            html.P([
                "Esta aplicación tiene como objetivo facilitar la consulta y análisis de eventos de amenaza ",
                "en Colombia, permitiendo visualizar y analizar datos históricos actualizados al año 2024 ",
                "de diferentes fuentes oficiales como UNGRD, DAGRAN y SIMMA."
            ]),
            html.P([
                "Desarrollado por: Hector Camilo Perez Contreras",
                html.Br(),
                "Geólogo, Especialista en Sistemas de Información Geográfica",
                html.Br(),
                "Magister (c) en Geoinformática",
                html.Br(),
                html.A("hectorcperez21@gmail.com", href="mailto:hectorcperez21@gmail.com")
            ])
        ])
    ], id="modal", size="lg"),

    # Contador de eventos
    dbc.Row([
        dbc.Col(html.Div(id='total-eventos', className="lead text-center fade-in"), width=12)
    ], className="mb-4"),

    # Mapa
    dbc.Row([
        dbc.Col([
            dbc.Card([
                dbc.CardHeader([
                    html.I(className="fas fa-map-marked-alt me-2"),
                    "Mapa de Localización",
                    html.I(className="fas fa-info-circle ms-2", 
                          id="info-mapa", 
                          style={'cursor': 'pointer', 'color': COLORS['primary']})
                ], className="fw-bold d-flex align-items-center"),
                dbc.CardBody([
                    dbc.Spinner(dcc.Graph(id='mapa-colombia'), color="primary")
                ]),
                dbc.Tooltip(
                    "Este mapa muestra la densidad de eventos por km² en cada municipio. "
                    "Los colores más intensos indican mayor densidad de eventos. "
                    "Al seleccionar un municipio, se resalta en rojo y se hace zoom sobre él.",
                    target="info-mapa",
                    placement="top"
                )
            ], style=CARD_STYLE)
        ], width=12, className="fade-in"),
    ], className="mb-4"),

    # Gráficos principales
    dbc.Row([
        dbc.Col([
            dbc.Card([
                dbc.CardHeader([
                    html.I(className="fas fa-chart-bar me-2"),
                    "Eventos por Tipo",
                    html.I(className="fas fa-info-circle ms-2", 
                          id="info-eventos-tipo", 
                          style={'cursor': 'pointer', 'color': COLORS['primary']})
                ], className="fw-bold d-flex align-items-center"),
                dbc.CardBody([
                    dbc.Spinner(dcc.Graph(id='grafico-eventos-tipo'), color="primary")
                ]),
                dbc.Tooltip(
                    "Muestra la distribución total de eventos por cada tipo. "
                    "La altura de las barras indica la cantidad de eventos registrados.",
                    target="info-eventos-tipo",
                    placement="top"
                )
            ], style=CARD_STYLE)
        ], width=8, className="fade-in"),
        dbc.Col([
            dbc.Card([
                dbc.CardHeader([
                    html.I(className="fas fa-chart-pie me-2"),
                    "Distribución por Fuente",
                    html.I(className="fas fa-info-circle ms-2", 
                          id="info-fuente", 
                          style={'cursor': 'pointer', 'color': COLORS['primary']})
                ], className="fw-bold d-flex align-items-center"),
                dbc.CardBody([
                    dbc.Spinner(dcc.Graph(id='grafico-fuente-datos'), color="primary")
                ]),
                dbc.Tooltip(
                    "Representa la proporción de eventos según su fuente de datos. "
                    "Cada sector del gráfico muestra el porcentaje de eventos por fuente.",
                    target="info-fuente",
                    placement="top"
                )
            ], style=CARD_STYLE)
        ], width=4, className="fade-in"),
    ], className="mb-4"),

    # Gráfico de eventos por tipo y fuente
    dbc.Row([
        dbc.Col([
            dbc.Card([
                dbc.CardHeader([
                    html.I(className="fas fa-chart-bar me-2"),
                    "Eventos por Tipo y Fuente",
                    html.I(className="fas fa-info-circle ms-2", 
                          id="info-tipo-fuente", 
                          style={'cursor': 'pointer', 'color': COLORS['primary']})
                ], className="fw-bold d-flex align-items-center"),
                dbc.CardBody([
                    dbc.Spinner(dcc.Graph(id='grafico-eventos-tipo-fuente'), color="primary")
                ]),
                dbc.Tooltip(
                    "Muestra la distribución de eventos por tipo y fuente de datos. "
                    "Las barras agrupadas permiten comparar la cantidad de eventos entre fuentes para cada tipo.",
                    target="info-tipo-fuente",
                    placement="top"
                )
            ], style=CARD_STYLE)
        ], width=12, className="fade-in"),
    ], className="mb-4"),

    # Serie temporal
    dbc.Row([
        dbc.Col([
            dbc.Card([
                dbc.CardHeader([
                    html.I(className="fas fa-chart-line me-2"),
                    "Serie Temporal de Eventos",
                    html.I(className="fas fa-info-circle ms-2", 
                          id="info-serie", 
                          style={'cursor': 'pointer', 'color': COLORS['primary']})
                ], className="fw-bold d-flex align-items-center"),
                dbc.CardBody([
                    dbc.Spinner(dcc.Graph(id='grafico-serie-tiempo'), color="primary")
                ]),
                dbc.Tooltip(
                    "Muestra la evolución temporal del número de eventos a lo largo de los años. "
                    "Permite identificar tendencias y patrones temporales en la ocurrencia de eventos.",
                    target="info-serie",
                    placement="top"
                )
            ], style=CARD_STYLE)
        ], width=12, className="fade-in"),
    ], className="mb-4"),

    # Componentes de descarga
    dcc.Download(id="descargar-resumen"),
    dcc.Download(id="descargar-detalle"),
    
    # Tablas
    dbc.Row([
        dbc.Col([
            html.H3([
                html.I(className="fas fa-table me-2"),
                "Resumen de Eventos"
            ], className="d-flex align-items-center"),
            html.Div(id='tabla-resumen', className="fade-in"),
            dbc.ButtonGroup([
                dbc.Button([
                    html.I(className="fas fa-file-excel me-2"),
                    "Descargar Resumen (Excel)"
                ], id="btn-descargar-resumen-excel", color="primary", className="mt-2 me-2"),
                dbc.Button([
                    html.I(className="fas fa-file-csv me-2"),
                    "Descargar Resumen (CSV)"
                ], id="btn-descargar-resumen-csv", color="secondary", className="mt-2"),
            ]),
        ], width=12),
    ], className="mb-4"),
    
    dbc.Row([
        dbc.Col([
            html.H3([
                html.I(className="fas fa-list-alt me-2"),
                "Detalle de Eventos"
            ], className="d-flex align-items-center"),
            html.Div(id='tabla-detallada', className="fade-in"),
            dbc.ButtonGroup([
                dbc.Button([
                    html.I(className="fas fa-file-excel me-2"),
                    "Descargar Detalle (Excel)"
                ], id="btn-descargar-detalle-excel", color="primary", className="mt-2 me-2"),
                dbc.Button([
                    html.I(className="fas fa-file-csv me-2"),
                    "Descargar Detalle (CSV)"
                ], id="btn-descargar-detalle-csv", color="secondary", className="mt-2"),
            ]),
        ], width=12),
    ], className="mb-5"),

    # Switch para Análisis Avanzados
    dbc.Row([
        dbc.Col([
            html.Hr(className="mb-4"),
            dbc.Switch(
                id='switch-analisis-avanzados',
                label=[
                    html.I(className="fas fa-microscope me-2"),
                    "Mostrar Análisis Avanzados"
                ],
                value=False,
                className="mb-3 d-flex align-items-center"
            )
        ], width=12)
    ]),

    # Contenedor para Análisis Avanzados
    html.Div([
        html.H2([
            html.I(className="fas fa-chart-area me-2"),
            "Análisis Avanzados"
        ], className="mt-4 mb-4 d-flex align-items-center fade-in"),
        
        dbc.Row([
            dbc.Col([
                dbc.Card([
                    dbc.CardHeader([
                        html.I(className="fas fa-calendar-alt me-2"),
                        "Distribución Temporal Mensual",
                        html.I(className="fas fa-info-circle ms-2", 
                              id="info-heatmap", 
                              style={'cursor': 'pointer', 'color': COLORS['primary']})
                    ], className="fw-bold d-flex align-items-center"),
                    dbc.CardBody([
                        dbc.Spinner(dcc.Graph(id='grafico-heatmap-temporal'), color="primary")
                    ]),
                    dbc.Tooltip(
                        "Mapa de calor que muestra la intensidad de eventos por mes y año. "
                        "Los colores más intensos indican mayor cantidad de eventos.",
                        target="info-heatmap",
                        placement="top"
                    )
                ], style=CARD_STYLE)
            ], width=12, className="fade-in"),
        ], className="mb-4"),

        dbc.Row([
            dbc.Col([
                dbc.Card([
                    dbc.CardHeader([
                        html.I(className="fas fa-chart-bar me-2"),
                        "Estacionalidad de Eventos",
                        html.I(className="fas fa-info-circle ms-2", 
                              id="info-estacionalidad", 
                              style={'cursor': 'pointer', 'color': COLORS['primary']})
                    ], className="fw-bold d-flex align-items-center"),
                    dbc.CardBody([
                        dbc.Spinner(dcc.Graph(id='grafico-estacionalidad'), color="primary")
                    ]),
                    dbc.Tooltip(
                        "Muestra la distribución mensual agregada de eventos. "
                        "Permite identificar los meses con mayor frecuencia de eventos.",
                        target="info-estacionalidad",
                        placement="top"
                    )
                ], style=CARD_STYLE)
            ], width=6, className="fade-in"),
            
            dbc.Col([
                dbc.Card([
                    dbc.CardHeader([
                        html.I(className="fas fa-project-diagram me-2"),
                        "Correlación entre Tipos de Eventos",
                        html.I(className="fas fa-info-circle ms-2", 
                              id="info-correlacion", 
                              style={'cursor': 'pointer', 'color': COLORS['primary']})
                    ], className="fw-bold d-flex align-items-center"),
                    dbc.CardBody([
                        dbc.Spinner(dcc.Graph(id='grafico-correlacion'), color="primary")
                    ]),
                    dbc.Tooltip(
                        "Matriz que muestra la correlación entre diferentes tipos de eventos. "
                        "Colores más intensos indican mayor correlación entre tipos de eventos.",
                        target="info-correlacion",
                        placement="top"
                    )
                ], style=CARD_STYLE)
            ], width=6, className="fade-in"),
        ], className="mb-4"),

        dbc.Row([
            dbc.Col([
                dbc.Card([
                    dbc.CardHeader([
                        html.I(className="fas fa-chart-line me-2"),
                        "Tendencias por Tipo de Evento",
                        html.I(className="fas fa-info-circle ms-2", 
                              id="info-tendencias", 
                              style={'cursor': 'pointer', 'color': COLORS['primary']})
                    ], className="fw-bold d-flex align-items-center"),
                    dbc.CardBody([
                        dbc.Spinner(dcc.Graph(id='grafico-tendencias'), color="primary")
                    ]),
                    dbc.Tooltip(
                        "Muestra la evolución temporal de cada tipo de evento. "
                        "Permite comparar tendencias entre diferentes tipos de eventos a lo largo del tiempo.",
                        target="info-tendencias",
                        placement="top"
                    )
                ], style=CARD_STYLE)
            ], width=12, className="fade-in"),
        ], className="mb-4"),
    ], id='contenedor-analisis-avanzados', style={'display': 'none'})
], style=CONTENT_STYLE)

app.index_string = '''
<!DOCTYPE html>
<html>
    <head>
        {%metas%}
        <title>{%title%}</title>
        {%favicon%}
        {%css%}
        <style>
            /* Animaciones de entrada */
            .fade-in {
                animation: fadeIn 0.5s ease-in;
                opacity: 0;
                animation-fill-mode: forwards;
            }
            
            @keyframes fadeIn {
                from { 
                    opacity: 0; 
                    transform: translateY(20px); 
                }
                to { 
                    opacity: 1; 
                    transform: translateY(0); 
                }
            }
            
            /* Efectos hover en las tarjetas */
            .card {
                transition: transform 0.3s ease, box-shadow 0.3s ease;
                border-radius: 8px;
            }
            
            .card:hover {
                transform: translateY(-5px);
                box-shadow: 0 4px 15px rgba(0,0,0,0.1);
            }
            
            /* Estilo para los iconos */
            .card-header i:not(.fa-info-circle) {
                color: #4285f4;
            }
            
            /* Animación para los spinners */
            .spinner-border {
                animation-duration: 1s;
            }
            
            /* Estilo para los tooltips */
            .tooltip {
                animation: tooltipFade 0.2s;
                font-size: 0.9rem;
            }
            
            @keyframes tooltipFade {
                from { opacity: 0; }
                to { opacity: 1; }
            }
            
            /* Estilos para los botones */
            .btn {
                transition: all 0.2s ease;
            }
            
            .btn:hover {
                transform: translateY(-2px);
                box-shadow: 0 2px 8px rgba(0,0,0,0.1);
            }
            
            /* Estilo para el switch */
            .custom-switch {
                padding-left: 2.25rem;
            }
            
            .custom-control-label {
                padding-top: 0.125rem;
            }
            
            /* Estilo para las tablas */
            .dash-table-container {
                border-radius: 8px;
                overflow: hidden;
                box-shadow: 0 2px 8px rgba(0,0,0,0.05);
            }
            
            /* Estilo para los encabezados */
            h2, h3 {
                color: #2c3e50;
                font-weight: 600;
            }
            
            /* Estilo para el navbar */
            .navbar {
                box-shadow: 0 2px 10px rgba(0,0,0,0.1);
            }
            
            /* Estilo para los íconos de info */
            .fa-info-circle {
                transition: color 0.2s ease;
            }
            
            .fa-info-circle:hover {
                color: #1a73e8 !important;
            }
        </style>
    </head>
    <body>
        {%app_entry%}
        <footer>
            {%config%}
            {%scripts%}
            {%renderer%}
        </footer>
    </body>
</html>
'''
# Layout principal
app.layout = html.Div([sidebar, content])

@app.callback(
    Output('tipo-evento-checklist', 'value'),
    Input('tipo-evento-checklist', 'value')
)
def update_checklist(selected_values):
    if 'todos' in selected_values:
        return ['todos'] + list(tipos_eventos)
    else:
        return [value for value in selected_values if value != 'todos']

# Modificar la función crear_grafico_serie_tiempo
def crear_grafico_serie_tiempo(df):
    """
    Crea un gráfico de línea que muestra la evolución temporal de eventos
    """
    try:
        if df.empty:
            return px.line(title="No hay datos disponibles")
        
        df = df.copy()
        df['FECHA'] = pd.to_datetime(df['FECHA'])
        eventos_por_año = df.groupby(df['FECHA'].dt.year).size().reset_index()
        eventos_por_año.columns = ['Año', 'Cantidad']
        
        fig = go.Figure()
        
        # Agregar área con relleno
        fig.add_trace(go.Scatter(
            x=eventos_por_año['Año'],
            y=eventos_por_año['Cantidad'],
            mode='lines+markers',
            line=dict(color='rgb(66, 133, 244)', width=2),
            fill='tozeroy',  # Relleno desde la línea hasta el eje x
            fillcolor='rgba(66, 133, 244, 0.2)',  # Color azul semi-transparente
            name='Eventos'
        ))
        
        fig.update_layout(
            title='Eventos por Año',
            xaxis_title='Año',
            yaxis_title='Número de eventos',
            showlegend=False,
            plot_bgcolor='white',
            paper_bgcolor='white',
            xaxis=dict(
                showgrid=True,
                gridcolor='rgba(0,0,0,0.1)'
            ),
            yaxis=dict(
                showgrid=True,
                gridcolor='rgba(0,0,0,0.1)'
            )
        )
        
        return fig
        
    except Exception as e:
        print(f"Error en crear_grafico_serie_tiempo: {str(e)}")
        return px.line(title="Error al crear el gráfico")

# Modificar el callback principal para incluir el nuevo input
@app.callback(
    [Output('total-eventos', 'children'),
     Output('mapa-colombia', 'figure'),
     Output('grafico-eventos-tipo', 'figure'),
     Output('grafico-fuente-datos', 'figure'),
     Output('grafico-eventos-tipo-fuente', 'figure'),
     Output('grafico-serie-tiempo', 'figure'),
     Output('tabla-resumen', 'children'),
     Output('tabla-detallada', 'children'),
     Output('grafico-heatmap-temporal', 'figure'),
     Output('grafico-estacionalidad', 'figure'),
     Output('grafico-correlacion', 'figure'),
     Output('grafico-tendencias', 'figure')],
    [Input('municipio-input', 'value'),
     Input('tipo-evento-checklist', 'value'),
     Input('fuentes-checklist', 'value')]
)
def actualizar_graficos(municipio, tipos_seleccionados, fuentes_seleccionadas):
    try:
        if not municipio:
            return ("No se ha seleccionado ningún municipio", crear_mapa_colombia(), 
                   px.bar(), px.pie(), px.bar(), px.line(), None, None,
                   px.imshow([[0]], title="No hay datos disponibles"),
                   px.bar(title="No hay datos disponibles"),
                   px.imshow([[0]], title="No hay datos disponibles"),
                   px.line(title="No hay datos disponibles"))

        if not fuentes_seleccionadas:
            return ("Debe seleccionar al menos una fuente de datos", crear_mapa_colombia(), 
                   px.bar(), px.pie(), px.bar(), px.line(), None, None,
                   px.imshow([[0]], title="No hay datos disponibles"),
                   px.bar(title="No hay datos disponibles"),
                   px.imshow([[0]], title="No hay datos disponibles"),
                   px.line(title="No hay datos disponibles"))

        municipio_norm = normalizar_texto(municipio)
        
        # Filtrar eventos del municipio seleccionado por cada fuente
        eventos_ungrd = pd.DataFrame()
        eventos_dagran = pd.DataFrame()
        eventos_simma = gpd.GeoDataFrame()

        if 'UNGRD' in fuentes_seleccionadas:
            eventos_ungrd = df_eventos_municipio[
                (df_eventos_municipio['MUNICIPIO'].apply(normalizar_texto).str.contains(municipio_norm, case=False, na=False)) & 
                (df_eventos_municipio['FUENTE'] == 'UNGRD')
            ].copy()

        if 'DAGRAN' in fuentes_seleccionadas:
            eventos_dagran = df_eventos_municipio[
                (df_eventos_municipio['MUNICIPIO'].apply(normalizar_texto).str.contains(municipio_norm, case=False, na=False)) & 
                (df_eventos_municipio['FUENTE'] == 'DAGRAN')
            ].copy()

        if 'SIMMA' in fuentes_seleccionadas:
            municipio_geom = gdf_municipios[gdf_municipios['MpNombre'].apply(normalizar_texto).str.contains(municipio_norm, case=False)].geometry
            if not municipio_geom.empty:
                eventos_simma = gdf_eventos_shp[gdf_eventos_shp.geometry.within(municipio_geom.iloc[0])].copy()
                eventos_simma['FUENTE'] = 'SIMMA'

        # Concatenar los eventos de las fuentes seleccionadas
        df_total_municipio = pd.concat([
            df for df in [eventos_ungrd, eventos_dagran, eventos_simma] 
            if not df.empty
        ])

        if df_total_municipio.empty:
            return (f"No se encontraron eventos para {municipio}", crear_mapa_colombia(), 
                   px.bar(), px.pie(), px.bar(), px.line(), None, None,
                   px.imshow([[0]], title="No hay datos disponibles"),
                   px.bar(title="No hay datos disponibles"),
                   px.imshow([[0]], title="No hay datos disponibles"),
                   px.line(title="No hay datos disponibles"))

        # Asegurarse de que la columna FECHA esté en formato datetime
        df_total_municipio['FECHA'] = pd.to_datetime(df_total_municipio['FECHA'], errors='coerce')
        
        # Normalizar los tipos de eventos
        df_total_municipio['TIPO'] = df_total_municipio['TIPO'].apply(normalizar_tipo_evento)
        
        # Filtrar por tipos de eventos seleccionados
        if tipos_seleccionados and 'todos' not in tipos_seleccionados:
            df_total_municipio = df_total_municipio[df_total_municipio['TIPO'].isin(tipos_seleccionados)]

        total_eventos = len(df_total_municipio)

        # Crear todos los gráficos
        fig_mapa = crear_mapa_colombia(municipio)
        fig_eventos_tipo = crear_grafico_eventos_tipo(df_total_municipio)
        fig_fuente_datos = crear_grafico_fuente_datos(df_total_municipio)
        fig_eventos_tipo_fuente = crear_grafico_eventos_tipo_fuente(df_total_municipio)
        fig_serie_tiempo = crear_grafico_serie_tiempo(df_total_municipio)
        tabla_resumen = crear_tabla_resumen(df_total_municipio, total_eventos)
        tabla_detallada = crear_tabla_detallada(df_total_municipio)
        
        # Crear los nuevos gráficos de análisis avanzado
        fig_heatmap = crear_grafico_serie_tiempo_mensual(df_total_municipio)
        fig_estacionalidad = crear_grafico_estacionalidad(df_total_municipio)
        fig_correlacion = crear_matriz_correlacion(df_total_municipio)
        fig_tendencias = crear_grafico_tendencias(df_total_municipio)

        return (f"Total de eventos en {municipio}: {total_eventos}",
                fig_mapa, fig_eventos_tipo, fig_fuente_datos,
                fig_eventos_tipo_fuente, fig_serie_tiempo,
                tabla_resumen, tabla_detallada,
                fig_heatmap, fig_estacionalidad,
                fig_correlacion, fig_tendencias)

    except Exception as e:
        print(f"Error en actualizar_graficos: {str(e)}")
        return ("Error", px.scatter(), px.bar(), px.pie(),
                px.bar(), px.line(), None, None,
                px.imshow([[0]]), px.bar(),
                px.imshow([[0]]), px.line())

# Callbacks para descargar tablas
@app.callback(
    Output("descargar-resumen", "data"),
    [Input("btn-descargar-resumen-excel", "n_clicks"),
     Input("btn-descargar-resumen-csv", "n_clicks")],
    [State('tabla-resumen', 'children')],
    prevent_initial_call=True
)
def descargar_resumen(n_clicks_excel, n_clicks_csv, tabla_resumen):
    ctx = dash.callback_context
    if not ctx.triggered:
        raise PreventUpdate
    button_id = ctx.triggered[0]['prop_id'].split('.')[0]
    
    if tabla_resumen is None:
        raise PreventUpdate
    
    df = pd.DataFrame(tabla_resumen['props']['data'])
    if button_id == "btn-descargar-resumen-excel":
        return dcc.send_data_frame(df.to_excel, "resumen_eventos.xlsx", sheet_name="Resumen")
    elif button_id == "btn-descargar-resumen-csv":
        return dcc.send_data_frame(df.to_csv, "resumen_eventos.csv", index=False)

@app.callback(
    Output("descargar-detalle", "data"),
    [Input("btn-descargar-detalle-excel", "n_clicks"),
     Input("btn-descargar-detalle-csv", "n_clicks")],
    [State('tabla-detallada', 'children')],
    prevent_initial_call=True
)
def descargar_detalle(n_clicks_excel, n_clicks_csv, tabla_detallada):
    ctx = dash.callback_context
    if not ctx.triggered:
        raise PreventUpdate
    button_id = ctx.triggered[0]['prop_id'].split('.')[0]
    
    if tabla_detallada is None:
        raise PreventUpdate
    
    df = pd.DataFrame(tabla_detallada['props']['data'])
    if button_id == "btn-descargar-detalle-excel":
        return dcc.send_data_frame(df.to_excel, "detalle_eventos.xlsx", sheet_name="Detalle")
    elif button_id == "btn-descargar-detalle-csv":
        return dcc.send_data_frame(df.to_csv, "detalle_eventos.csv", index=False)

# Agregar una función para contar eventos por municipio
def contar_eventos_por_municipio(df_eventos_municipio, gdf_eventos_shp, gdf_municipios):
    # Contar eventos del DataFrame
    eventos_df = df_eventos_municipio['MUNICIPIO'].value_counts().reset_index()
    eventos_df.columns = ['MpNombre', 'Eventos']
    
    # Contar eventos del GeoDataFrame
    eventos_shp = gdf_eventos_shp.sjoin(gdf_municipios, how="inner", predicate="within")
    eventos_shp = eventos_shp['MpNombre'].value_counts().reset_index()
    eventos_shp.columns = ['MpNombre', 'Eventos']
    
    # Combinar ambos conteos
    eventos_total = pd.concat([eventos_df, eventos_shp]).groupby('MpNombre').sum().reset_index()
    
    # Merge con gdf_municipios
    gdf_municipios_eventos = gdf_municipios.merge(eventos_total, on='MpNombre', how='left')
    gdf_municipios_eventos['Eventos'] = gdf_municipios_eventos['Eventos'].fillna(0)
    
    # Calcular el área en km²
    gdf_municipios_eventos['Area_km2'] = gdf_municipios_eventos.to_crs({'proj':'cea'}).area / 10**6
    
    # Calcular la densidad de eventos por km²
    gdf_municipios_eventos['Densidad_Eventos'] = gdf_municipios_eventos['Eventos'] / gdf_municipios_eventos['Area_km2']
    
    return gdf_municipios_eventos

# Modificar la función crear_mapa_colombia
def crear_mapa_colombia(municipio_seleccionado=None):
    try:
        gdf_municipios_eventos = contar_eventos_por_municipio(df_eventos_municipio, gdf_eventos_shp, gdf_municipios)
        
        fig = go.Figure(go.Choroplethmapbox(
            geojson=gdf_municipios_eventos.__geo_interface__,
            locations=gdf_municipios_eventos.index,
            z=gdf_municipios_eventos['Densidad_Eventos'],
            colorscale="Viridis",
            marker_opacity=0.7,
            marker_line_width=0,
            colorbar=dict(
                title=dict(
                    text="Densidad de eventos por km²",
                    side='right',
                    font=dict(size=12),
                ),
                thickness=15,
                len=0.75,
                yanchor='middle',
                y=0.5,
                ticks='outside'
            ),
        ))

        # Configuración inicial del mapa
        layout_inicial = dict(
            mapbox_style="light",
            mapbox=dict(
                accesstoken=mapbox_access_token,
                center={"lat": 4.5709, "lon": -74.2973},
                zoom=4
            ),
            margin={"r":0,"t":0,"l":0,"b":0},
            uirevision='constant'  # Mantener el estado del UI entre actualizaciones
        )
        
        fig.update_layout(layout_inicial)
        
        if municipio_seleccionado:
            municipio_norm = normalizar_texto(municipio_seleccionado)
            municipio_geom = gdf_municipios_eventos[
                gdf_municipios_eventos['MpNombre'].apply(normalizar_texto).str.contains(municipio_norm, case=False)
            ]
            
            if not municipio_geom.empty:
                # Calcular el centroide y los límites del municipio
                municipio_geom_proj = municipio_geom.to_crs('EPSG:4326')
                bounds = municipio_geom_proj.geometry.total_bounds  # [minx, miny, maxx, maxy]
                
                # Calcular el centro
                center_lon = (bounds[0] + bounds[2]) / 2
                center_lat = (bounds[1] + bounds[3]) / 2
                
                # Calcular el zoom basado en la extensión del municipio
                lon_range = bounds[2] - bounds[0]
                lat_range = bounds[3] - bounds[1]
                
                # Ajustar la fórmula del zoom para mostrar más contexto
                zoom = min(8, max(5, -1.2 * math.log(max(lon_range, lat_range)) + 10))
                
                # Agregar el municipio resaltado
                fig.add_choroplethmapbox(
                    geojson=municipio_geom.__geo_interface__,
                    locations=municipio_geom.index,
                    z=municipio_geom['Densidad_Eventos'],
                    colorscale=[[0, "red"], [1, "red"]],
                    marker_opacity=0.8,
                    showscale=False
                )
                
                # Actualizar la vista del mapa con los nuevos valores
                fig.update_layout(
                    mapbox=dict(
                        center=dict(lat=center_lat, lon=center_lon),
                        zoom=zoom
                    ),
                    uirevision=municipio_seleccionado  # Actualizar uirevision con el municipio actual
                )
        
        return fig
    except Exception as e:
        print(f"Error en crear_mapa_colombia: {str(e)}")
        return go.Figure()

# Agregar un callback para validar que siempre haya al menos una fuente seleccionada
@app.callback(
    Output('fuentes-checklist', 'value'),
    [Input('fuentes-checklist', 'value')]
)
def validar_fuentes_seleccionadas(value):
    if not value:  # Si no hay fuentes seleccionadas
        return ['UNGRD']  # Devolver al menos una fuente por defecto
    return value

def crear_grafico_serie_tiempo_mensual(df):
    try:
        if df.empty:
            return px.imshow([[0]], title="No hay datos disponibles")
            
        # Filtrar solo datos de UNGRD
        df = df[df['FUENTE'] == 'UNGRD'].copy()
        df['FECHA'] = pd.to_datetime(df['FECHA'], errors='coerce')
        df = df.dropna(subset=['FECHA'])
        
        if df.empty:
            return px.imshow([[0]], title="No hay datos disponibles")
            
        df['Año'] = df['FECHA'].dt.year
        df['Mes'] = df['FECHA'].dt.month
        
        eventos_por_mes = df.groupby(['Año', 'Mes']).size().reset_index(name='Cantidad')
        eventos_pivot = eventos_por_mes.pivot(index='Año', columns='Mes', values='Cantidad').fillna(0)
        
        fig = px.imshow(eventos_pivot,
                       labels=dict(x="Mes", y="Año", color="Cantidad de Eventos"),
                       title="Distribución Mensual de Eventos por Año",
                       aspect="auto",
                       color_continuous_scale="Viridis")
        
        # Actualizar la orientación del título de la barra de color
        fig.update_layout(
            coloraxis_colorbar=dict(
                title=dict(
                    text="Cantidad de Eventos",
                    side='right',
                    font=dict(size=12),
                ),
                thickness=15,
                len=0.75,
                yanchor='middle',
                y=0.5,
                ticks='outside'
            ),
            plot_bgcolor='white',
            paper_bgcolor='white',
            font={'color': COLORS['secondary'], 'size': 12},
            title_font={'size': 16, 'color': COLORS['dark']},
            xaxis = dict(
                ticktext=['Ene', 'Feb', 'Mar', 'Abr', 'May', 'Jun', 
                         'Jul', 'Ago', 'Sep', 'Oct', 'Nov', 'Dic'],
                tickvals=list(range(12)),
                gridcolor='rgba(0,0,0,0.1)',
                showgrid=True
            ),
            yaxis=dict(
                gridcolor='rgba(0,0,0,0.1)',
                showgrid=True
            ),
            margin=dict(l=50, r=50, t=50, b=50)
        )
        return fig
    except Exception as e:
        print(f"Error en crear_grafico_serie_tiempo_mensual: {str(e)}")
        return px.imshow([[0]], title="Error al crear el gráfico")

def crear_grafico_estacionalidad(df):
    try:
        if df.empty:
            return px.bar(title="No hay datos disponibles")
            
        # Filtrar solo datos de UNGRD
        df = df[df['FUENTE'] == 'UNGRD'].copy()
        df['FECHA'] = pd.to_datetime(df['FECHA'], errors='coerce')
        df = df.dropna(subset=['FECHA'])
        
        if df.empty:
            return px.bar(title="No hay datos disponibles")
            
        df['Mes'] = df['FECHA'].dt.month
        eventos_por_mes = df.groupby('Mes').size().reset_index(name='Cantidad')
        
        meses = ['Enero', 'Febrero', 'Marzo', 'Abril', 'Mayo', 'Junio',
                 'Julio', 'Agosto', 'Septiembre', 'Octubre', 'Noviembre', 'Diciembre']
        eventos_por_mes['Nombre_Mes'] = eventos_por_mes['Mes'].apply(lambda x: meses[int(x)-1])
        
        fig = go.Figure()
        fig.add_trace(go.Bar(
            x=eventos_por_mes['Nombre_Mes'],
            y=eventos_por_mes['Cantidad'],
            marker_color=GRAPH_COLORS[0],
            marker_line_color='white',
            marker_line_width=0.5
        ))
        
        fig.update_layout(
            title='Distribución Mensual de Eventos',
            title_font={'size': 16, 'color': COLORS['dark']},
            plot_bgcolor='white',
            paper_bgcolor='white',
            font={'color': COLORS['secondary'], 'size': 12},
            xaxis=dict(
                title='Mes',
                titlefont_size=12,
                tickfont_size=10,
                gridcolor='rgba(0,0,0,0.1)',
                showgrid=True
            ),
            yaxis=dict(
                title='Número de eventos',
                titlefont_size=12,
                tickfont_size=10,
                gridcolor='rgba(0,0,0,0.1)',
                showgrid=True
            ),
            margin=dict(l=50, r=50, t=50, b=50),
            showlegend=False
        )
        return fig
    except Exception as e:
        print(f"Error en crear_grafico_estacionalidad: {str(e)}")
        return px.bar(title="Error al crear el gráfico")

def crear_matriz_correlacion(df):
    try:
        if df.empty:
            return px.imshow([[0]], title="No hay datos disponibles")
            
        df = df.copy()
        df['FECHA'] = pd.to_datetime(df['FECHA'], errors='coerce')
        df = df.dropna(subset=['FECHA'])
        
        if df.empty:
            return px.imshow([[0]], title="No hay datos disponibles")
            
        df['Mes_Año'] = df['FECHA'].dt.strftime('%Y-%m')
        
        eventos_pivot = pd.pivot_table(
            df,
            index='Mes_Año',
            columns='TIPO',
            aggfunc='size',
            fill_value=0
        )
        
        corr = eventos_pivot.corr()
        
        fig = px.imshow(
            corr,
            color_continuous_scale='RdBu_r',  # Invertir la escala de colores
            aspect='auto',
            title='Correlación entre Tipos de Eventos'
        )
        
        fig.update_layout(
            plot_bgcolor='white',
            paper_bgcolor='white',
            font={'color': COLORS['secondary'], 'size': 12},
            title_font={'size': 16, 'color': COLORS['dark']},
            xaxis={'title': 'Tipo de Evento', 'tickangle': -45},
            yaxis={'title': 'Tipo de Evento'},
            margin=dict(l=50, r=50, t=50, b=100),
            height=700
        )
        return fig
    except Exception as e:
        print(f"Error en crear_matriz_correlacion: {str(e)}")
        return px.imshow([[0]], title="Error al crear el gráfico")

def crear_grafico_tendencias(df):
    try:
        if df.empty:
            return px.line(title="No hay datos disponibles")
            
        df = df.copy()
        df['FECHA'] = pd.to_datetime(df['FECHA'], errors='coerce')
        df = df.dropna(subset=['FECHA'])
        
        if df.empty:
            return px.line(title="No hay datos disponibles")
            
        df['Año'] = df['FECHA'].dt.year
        eventos_por_año_tipo = df.groupby(['Año', 'TIPO']).size().reset_index(name='Cantidad')
        
        fig = go.Figure()
        
        for i, tipo in enumerate(eventos_por_año_tipo['TIPO'].unique()):
            datos_tipo = eventos_por_año_tipo[eventos_por_año_tipo['TIPO'] == tipo]
            fig.add_trace(go.Scatter(
                x=datos_tipo['Año'],
                y=datos_tipo['Cantidad'],
                name=tipo,
                mode='lines+markers',
                line=dict(color=GRAPH_COLORS[i % len(GRAPH_COLORS)], width=2),
                marker=dict(size=6)
            ))
        
        fig.update_layout(
            title='Tendencias por Tipo de Evento',
            title_font={'size': 16, 'color': COLORS['dark']},
            plot_bgcolor='white',
            paper_bgcolor='white',
            font={'color': COLORS['secondary'], 'size': 12},
            xaxis=dict(
                title='Año',
                titlefont_size=12,
                tickfont_size=10,
                gridcolor='rgba(0,0,0,0.1)',
                showgrid=True
            ),
            yaxis=dict(
                title='Número de eventos',
                titlefont_size=12,
                tickfont_size=10,
                gridcolor='rgba(0,0,0,0.1)',
                showgrid=True
            ),
            legend=dict(
                yanchor="top",
                y=0.99,
                xanchor="left",
                x=1.02,
                bgcolor='rgba(255,255,255,0.8)'
            ),
            margin=dict(l=50, r=150, t=50, b=50),  # Ajustar margen derecho para la leyenda
            showlegend=True,
            hovermode='x unified'
        )
        return fig
    except Exception as e:
        print(f"Error en crear_grafico_tendencias: {str(e)}")
        return px.line(title="Error al crear el gráfico")

def crear_grafico_eventos_tipo(df):
    """
    Crea un gráfico de barras que muestra el total de eventos por tipo
    """
    try:
        if df.empty:
            return px.bar(title="No hay datos disponibles")
        
        # Contar eventos por tipo
        eventos_por_tipo = df.groupby('TIPO').size().reset_index(name='Cantidad')
        # Ordenar de mayor a menor
        eventos_por_tipo = eventos_por_tipo.sort_values('Cantidad', ascending=False)
        
        fig = px.bar(
            eventos_por_tipo, 
            x='TIPO', 
            y='Cantidad',
            title='Total Eventos por Tipo',
            labels={'Cantidad': 'Número de eventos', 'TIPO': 'Tipo de Evento'}
        )
        
        fig.update_layout(xaxis_tickangle=-45)
        fig.update_traces(
            marker_color=GRAPH_COLORS[0],
            marker_line_color='white',
            marker_line_width=0.5
        )
        fig.update_layout(
            plot_bgcolor='white',
            paper_bgcolor='white',
            font={'color': COLORS['secondary']},
            title_font_color=COLORS['dark']
        )
        return fig
        
    except Exception as e:
        print(f"Error en crear_grafico_eventos_tipo: {str(e)}")
        return px.bar(title="Error al crear el gráfico")

def crear_grafico_fuente_datos(df):
    """
    Crea un gráfico de torta que muestra la distribución por fuente de datos
    """
    try:
        if df.empty:
            return px.pie(title="No hay datos disponibles")
        
        eventos_por_fuente = df['FUENTE'].value_counts()
        
        fig = go.Figure(data=[go.Pie(
            labels=eventos_por_fuente.index,
            values=eventos_por_fuente.values,
            hole=0.4,  # Convertirlo en un donut chart para un look más moderno
            marker=dict(colors=GRAPH_COLORS),
            textinfo='label+percent',
            textposition='outside',
            textfont=dict(size=12, color=COLORS['dark'])
        )])
        
        fig.update_layout(
            title='Distribución por Fuente de Datos',
            title_font={'size': 16, 'color': COLORS['dark']},
            plot_bgcolor='white',
            paper_bgcolor='white',
            font={'color': COLORS['secondary'], 'size': 12},
            showlegend=False,
            margin=dict(l=50, r=50, t=50, b=50)
        )
        return fig
    except Exception as e:
        print(f"Error en crear_grafico_fuente_datos: {str(e)}")
        return px.pie(title="Error al crear el gráfico")

def crear_grafico_eventos_tipo_fuente(df):
    """
    Crea un gráfico de barras agrupadas por tipo de evento y fuente
    """
    try:
        if df.empty:
            return px.bar(title="No hay datos disponibles")
        
        eventos_por_tipo_fuente = df.groupby(['TIPO', 'FUENTE']).size().reset_index(name='Cantidad')
        total_por_tipo = eventos_por_tipo_fuente.groupby('TIPO')['Cantidad'].sum().sort_values(ascending=False)
        orden_tipos = total_por_tipo.index.tolist()
        
        fig = go.Figure()
        
        # Definir posiciones de las barras para cada fuente
        fuentes = df['FUENTE'].unique()
        width = 0.25  # Ancho de cada barra
        offsets = np.linspace(-(width * (len(fuentes)-1)/2), width * (len(fuentes)-1)/2, len(fuentes))
        
        for i, fuente in enumerate(fuentes):
            datos_fuente = eventos_por_tipo_fuente[eventos_por_tipo_fuente['FUENTE'] == fuente]
            fig.add_trace(go.Bar(
                name=fuente,
                x=datos_fuente['TIPO'],
                y=datos_fuente['Cantidad'],
                marker_color=GRAPH_COLORS[i],
                offset=offsets[i],
                width=width
            ))
        
        fig.update_layout(
            title='Eventos por Tipo y Fuente',
            title_font={'size': 16, 'color': COLORS['dark']},
            plot_bgcolor='white',
            paper_bgcolor='white',
            font={'color': COLORS['secondary'], 'size': 12},
            xaxis=dict(
                title='Tipo de Evento',
                titlefont_size=12,
                tickfont_size=10,
                tickangle=-45,
                gridcolor='rgba(0,0,0,0.1)',
                showgrid=True
            ),
            yaxis=dict(
                title='Número de eventos',
                titlefont_size=12,
                tickfont_size=10,
                gridcolor='rgba(0,0,0,0.1)',
                showgrid=True
            ),
            barmode='group',
            bargap=0.15,
            bargroupgap=0.1,
            legend=dict(
                title='Fuente',
                yanchor="top",
                y=0.99,
                xanchor="left",
                x=1.02,
                bgcolor='rgba(255,255,255,0.8)'
            ),
            margin=dict(l=50, r=150, t=50, b=100)  # Ajustar márgenes
        )
        
        # Ordenar las categorías del eje x
        fig.update_xaxes(categoryorder='array', categoryarray=orden_tipos)
        
        return fig
    except Exception as e:
        print(f"Error en crear_grafico_eventos_tipo_fuente: {str(e)}")
        return px.bar(title="Error al crear el gráfico")

def crear_tabla_resumen(df, total_eventos):
    """
    Crea una tabla resumen con estadísticas básicas
    """
    try:
        if df.empty:
            return None
        
        eventos_por_fuente = df['FUENTE'].value_counts()
        datos_relevantes = pd.DataFrame({
            'Fuente': eventos_por_fuente.index,
            'Cantidad de Eventos': eventos_por_fuente.values
        })
        
        datos_relevantes = pd.concat([
            datos_relevantes,
            pd.DataFrame({
                'Fuente': ['Total'],
                'Cantidad de Eventos': [total_eventos]
            })
        ])
        
        return dash_table.DataTable(
            data=datos_relevantes.to_dict('records'),
            columns=[{'name': i, 'id': i} for i in datos_relevantes.columns],
            style_cell={'textAlign': 'left', 'padding': '5px'},
            style_header={'backgroundColor': 'rgb(230, 230, 230)', 'fontWeight': 'bold'}
        )
        
    except Exception as e:
        print(f"Error en crear_tabla_resumen: {str(e)}")
        return None

def crear_tabla_detallada(df):
    """
    Crea una tabla detallada con todos los eventos
    """
    try:
        if df.empty:
            return None
        
        columnas = ['FUENTE', 'TIPO', 'FECHA', 'COMENTARIOS']
        df_detalle = df[columnas].copy()
        
        return dash_table.DataTable(
            data=df_detalle.to_dict('records'),
            columns=[{'name': i, 'id': i} for i in columnas],
            page_size=10,
            style_cell={'textAlign': 'left', 'padding': '5px'},
            style_header={'backgroundColor': 'rgb(230, 230, 230)', 'fontWeight': 'bold'}
        )
        
    except Exception as e:
        print(f"Error en crear_tabla_detallada: {str(e)}")
        return None

# Agregar nuevo callback para el switch de análisis avanzados
@app.callback(
    Output('contenedor-analisis-avanzados', 'style'),
    [Input('switch-analisis-avanzados', 'value')]
)
def toggle_analisis_avanzados(mostrar):
    if mostrar:
        return {'display': 'block'}
    return {'display': 'none'}

# Agregar callback para el modal
@app.callback(
    Output("modal", "is_open"),
    [Input("open-modal", "n_clicks")],
    [State("modal", "is_open")],
)
def toggle_modal(n1, is_open):
    if n1:
        return not is_open
    return is_open

# Asegurarnos que todos los tooltips estén correctamente configurados
# Agregar estos tooltips después de las definiciones de las cards correspondientes

# Para el gráfico de eventos por tipo
dbc.Tooltip(
    "Muestra la distribución total de eventos por cada tipo. "
    "La altura de las barras indica la cantidad de eventos registrados.",
    target="info-eventos-tipo",
    placement="top"
),

# Para el gráfico de fuente de datos
dbc.Tooltip(
    "Representa la proporción de eventos según su fuente de datos (UNGRD, DAGRAN, SIMMA). "
    "Cada sector del gráfico muestra el porcentaje de eventos por fuente.",
    target="info-fuente",
    placement="top"
),

# Para el gráfico de eventos por tipo y fuente
dbc.Tooltip(
    "Muestra la distribución de eventos por tipo y fuente de datos. "
    "Las barras agrupadas permiten comparar la cantidad de eventos entre fuentes para cada tipo.",
    target="info-tipo-fuente",
    placement="top"
),

# Para el gráfico de serie temporal
dbc.Tooltip(
    "Muestra la evolución temporal del número de eventos a lo largo de los años. "
    "Permite identificar tendencias y patrones temporales en la ocurrencia de eventos.",
    target="info-serie",
    placement="top"
),

# Para el gráfico de heatmap temporal
dbc.Tooltip(
    "Mapa de calor que muestra la intensidad de eventos por mes y año. "
    "Los colores más intensos indican mayor cantidad de eventos. "
    "Permite identificar patrones estacionales y años atípicos.",
    target="info-heatmap",
    placement="top"
),

# Para el gráfico de estacionalidad
dbc.Tooltip(
    "Muestra la distribución mensual agregada de eventos. "
    "Permite identificar los meses con mayor frecuencia de eventos.",
    target="info-estacionalidad",
    placement="top"
),

# Para el gráfico de correlación
dbc.Tooltip(
    "Matriz que muestra la correlación entre diferentes tipos de eventos. "
    "Colores más intensos indican mayor correlación entre tipos de eventos.",
    target="info-correlacion",
    placement="top"
),

# Para el gráfico de tendencias
dbc.Tooltip(
    "Muestra la evolución temporal de cada tipo de evento. "
    "Permite comparar tendencias entre diferentes tipos de eventos a lo largo del tiempo.",
    target="info-tendencias",
    placement="top"
)

# Agregar estilos CSS personalizados
app.index_string = '''
<!DOCTYPE html>
<html>
    <head>
        {%metas%}
        <title>Eventos de Amenaza Colombia</title>
        {%favicon%}
        {%css%}
        <style>
            /* Estilos personalizados para checkboxes */
            .checklist-custom label:hover {
                color: #0d6efd;
                cursor: pointer;
            }
            
            /* Mejorar apariencia de los tooltips */
            .tooltip {
                font-size: 0.875rem;
                opacity: 0.95 !important;
            }
            
            /* Estilo para los spinners */
            .spinner-border {
                width: 1.5rem;
                height: 1.5rem;
            }
            
            /* Mejorar la apariencia de los gráficos */
            .js-plotly-plot .plotly .modebar {
                opacity: 0.3;
            }
            
            .js-plotly-plot .plotly .modebar:hover {
                opacity: 1;
            }
            
            /* Animaciones y transiciones suaves */
            * {
                transition: all 0.3s ease-in-out;
            }
            
            .card {
                transition: transform 0.2s;
            }
            
            .card:hover {
                transform: translateY(-2px);
            }
            
            /* Mejorar la apariencia del scrollbar */
            ::-webkit-scrollbar {
                width: 8px;
            }
            
            ::-webkit-scrollbar-track {
                background: #f1f1f1;
            }
            
            ::-webkit-scrollbar-thumb {
                background: #888;
                border-radius: 4px;
            }
            
            ::-webkit-scrollbar-thumb:hover {
                background: #555;
            }
        </style>
    </head>
    <body>
        {%app_entry%}
        <footer>
            {%config%}
            {%scripts%}
            {%renderer%}
        </footer>
    </body>
</html>
'''

# Ejecutar la aplicación
if __name__ == '__main__':
    if not is_port_in_use(8050):
        app.run_server(debug=False, host='127.0.0.1', port=8050)
    else:
        print("La aplicación ya está corriendo en el puerto 8050")