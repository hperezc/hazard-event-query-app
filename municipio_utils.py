import unicodedata


def normalizar_texto(texto):
    if texto is None:
        return ""

    texto_sin_tildes = "".join(
        c
        for c in unicodedata.normalize("NFD", str(texto))
        if unicodedata.category(c) != "Mn"
    )
    return texto_sin_tildes.upper().strip()


def parsear_municipio_fuente(valor, departamento_predeterminado=None):
    if valor is None:
        return departamento_predeterminado, None

    valor = str(valor).strip()
    if not valor:
        return departamento_predeterminado, None

    if "/" in valor:
        departamento, municipio = valor.split("/", 1)
        return departamento.strip(), municipio.strip()

    return departamento_predeterminado, valor


def crear_clave_municipio(departamento, municipio):
    return f"{normalizar_texto(departamento)}|{normalizar_texto(municipio)}"


def crear_etiqueta_municipio(departamento, municipio):
    return f"{municipio} ({departamento})"


def construir_opciones_municipio(municipios):
    municipios_unicos = {}

    for departamento, municipio in municipios:
        if not departamento or not municipio:
            continue

        clave = crear_clave_municipio(departamento, municipio)
        if clave not in municipios_unicos:
            municipios_unicos[clave] = crear_etiqueta_municipio(departamento, municipio)

    return [
        {"label": etiqueta, "value": clave}
        for clave, etiqueta in sorted(
            municipios_unicos.items(),
            key=lambda item: normalizar_texto(item[1]),
        )
    ]
