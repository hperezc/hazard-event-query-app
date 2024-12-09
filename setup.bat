@echo off
echo Instalando dependencias...
SET PATH=%~dp0python;%PATH%

REM Descargar get-pip.py
echo Descargando pip...
curl https://bootstrap.pypa.io/get-pip.py -o get-pip.py
"%~dp0python\python.exe" get-pip.py

REM Instalar dependencias una por una
echo.
echo Instalando dash...
"%~dp0python\python.exe" -m pip install dash
echo.
echo Instalando dash-bootstrap-components...
"%~dp0python\python.exe" -m pip install dash-bootstrap-components
echo.
echo Instalando pandas y relacionados...
"%~dp0python\python.exe" -m pip install pandas openpyxl xlrd xlwt
echo.
echo Instalando geopandas...
"%~dp0python\python.exe" -m pip install geopandas
echo.
echo Instalando sqlalchemy...
"%~dp0python\python.exe" -m pip install sqlalchemy
echo.
echo Instalando plotly...
"%~dp0python\python.exe" -m pip install plotly
echo.
echo Instalando python-dotenv...
"%~dp0python\python.exe" -m pip install python-dotenv
echo.
echo Instalando psycopg2-binary...
"%~dp0python\python.exe" -m pip install psycopg2-binary
echo.
echo Instalando numpy...
"%~dp0python\python.exe" -m pip install numpy
echo.
echo Instalando shapely...
"%~dp0python\python.exe" -m pip install shapely

del get-pip.py

echo.
echo Instalacion completada!
echo.
pause