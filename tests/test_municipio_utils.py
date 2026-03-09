import unittest
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from municipio_utils import (
    construir_opciones_municipio,
    crear_clave_municipio,
    crear_etiqueta_municipio,
    parsear_municipio_fuente,
)


class MunicipioUtilsTestCase(unittest.TestCase):
    def test_parsea_departamento_y_municipio_desde_ungrd(self):
        departamento, municipio = parsear_municipio_fuente("ANTIOQUIA/MEDELLIN")

        self.assertEqual(departamento, "ANTIOQUIA")
        self.assertEqual(municipio, "MEDELLIN")

    def test_aplica_departamento_predeterminado_si_no_viene_en_la_fuente(self):
        departamento, municipio = parsear_municipio_fuente("Tamesis", "Antioquia")

        self.assertEqual(departamento, "Antioquia")
        self.assertEqual(municipio, "Tamesis")

    def test_construye_clave_normalizada(self):
        self.assertEqual(
            crear_clave_municipio("Bogotá, D.C.", "Cáqueza"),
            "BOGOTA, D.C.|CAQUEZA",
        )

    def test_construye_opciones_unicas_y_ordenadas(self):
        opciones = construir_opciones_municipio(
            [
                ("Meta", "Granada"),
                ("Antioquia", "Granada"),
                ("Meta", "Granada"),
                ("Cundinamarca", "Cáqueza"),
            ]
        )

        self.assertEqual(
            opciones,
            [
                {
                    "label": "Cáqueza (Cundinamarca)",
                    "value": "CUNDINAMARCA|CAQUEZA",
                },
                {
                    "label": "Granada (Antioquia)",
                    "value": "ANTIOQUIA|GRANADA",
                },
                {
                    "label": "Granada (Meta)",
                    "value": "META|GRANADA",
                },
            ],
        )

    def test_construye_etiqueta_legible(self):
        self.assertEqual(
            crear_etiqueta_municipio("Antioquia", "Granada"),
            "Granada (Antioquia)",
        )


if __name__ == "__main__":
    unittest.main()
