import json
import logging
import os
import re
import subprocess
import time
from pathlib import Path
from typing import Any, Dict, List
from urllib.parse import urlparse

import coloredlogs
import undetected_chromedriver as uc
from bs4 import BeautifulSoup
from colorama import Back, Fore, Style, init
from pyfiglet import Figlet

# --- CONSTANTES DE CONFIGURACIÓN ---
BASE_URL = "https://escuelafullstack.com"
COOKIES_FILE = Path("cookies.json")
DOWNLOAD_TIMEOUT_SECONDS = 15  # Tiempo de espera para que los elementos carguen
LOG_LEVEL = logging.INFO
LOG_DIR = "logs"

# --- CONFIGURACIÓN DE LOGGING Y BANNER ---
def setup_logging_and_banner():
    """
    Configura el logger para que muestre mensajes en la consola (con colores)
    y los guarde en un archivo de texto (sin colores). Muestra el banner inicial.
    """

    log_filename = f"{time.strftime('%d-%m-%Y_%H-%M-%S')}.log"

    if not os.path.exists(LOG_DIR):
        os.makedirs(LOG_DIR)

    log_filepath = os.path.join(LOG_DIR, log_filename)

    # Formato y estilos para la consola
    log_format_console = '[%(asctime)s] [%(name)s] [%(funcName)s:%(lineno)d] [%(levelname)s]: %(message)s'
    log_date_format = '%d-%m-%Y %H:%M:%S'
    log_styles = {
        'info': {'color': 'white'},
        'warning': {'color': 'yellow'},
        'error': {'color': 'red'},
        'critical': {'bold': True, 'color': 'red'},
    }

    logger = logging.getLogger('fs-downloader')
    logger.setLevel(LOG_LEVEL) # Establecer el nivel en el logger principal
    coloredlogs.install(level=LOG_LEVEL, logger=logger, fmt=log_format_console, datefmt=log_date_format, level_styles=log_styles)

    # --- CONFIGURACIÓN PARA EL ARCHIVO DE LOG ---
    # 1. Crear el handler para el archivo.
    file_handler = logging.FileHandler(log_filepath, mode='w', encoding='utf-8')
    file_handler.setLevel(LOG_LEVEL)

    # 2. Crear un formateador para los logs del archivo (sin colores).
    log_format_file = logging.Formatter('[%(asctime)s] [%(levelname)s] [%(funcName)s] %(message)s', datefmt=log_date_format)

    # 3. Asignar el formateador al handler del archivo.
    file_handler.setFormatter(log_format_file)

    # 4. Añadir el handler del archivo al logger principal.
    logger.addHandler(file_handler)

    init(autoreset=True)
    font = Figlet(font='slant')
    script_title = 'FS-Downloader'
    print(Fore.YELLOW + Style.BRIGHT + font.renderText(script_title))
    print(Back.YELLOW + Style.BRIGHT + "Created by alphaDRM")
    print()
    return logger


logger = setup_logging_and_banner()


# --- FUNCIONES AUXILIARES ---

def sanitize_name(name: str) -> str:
    """Limpia la cadena para que sea un nombre de archivo/carpeta válido."""
    return re.sub(r'[<>:"/\\|?*]', '_', name).strip()


def split_name(name: str, base_path, limite=200) -> str:
    """
    Calcula la longitud máxima de un nombre de archivo y lo recorta si la ruta absoluta
    excede un límite de caracteres.
    """
    # Ruta absoluta del directorio donde se guardará el archivo
    ruta_base = os.path.abspath(base_path)

    # Unir la ruta base con el nombre de archivo original
    ruta_completa = os.path.join(ruta_base, name)

    if len(ruta_completa) <= limite:
        return name

    # Calcular cuánto se puede usar para el nombre, restando la longitud de la base y el separador
    base_len = len(os.path.join(ruta_base, ""))
    espacio_disponible = limite - base_len

    nombre_recortado = name[:espacio_disponible]

    return nombre_recortado.rstrip()


# --- FUNCIONES PRINCIPALES DEL SCRAPER ---

def create_driver() -> uc.Chrome:
    """Inicializa y retorna una instancia del WebDriver."""
    logger.info("Iniciando el navegador Chrome...")
    driver = uc.Chrome()
    driver.maximize_window()
    return driver


def login_with_cookies(driver: uc.Chrome):
    """Carga las cookies desde un archivo JSON para autenticarse."""
    if not COOKIES_FILE.is_file():
        logger.error(f"El archivo de cookies '{COOKIES_FILE}' no fue encontrado.")
        logger.warning("Por favor, asegúrate de tener un archivo de cookies válido en la misma carpeta.")
        driver.quit()
        exit()

    logger.info(f"Cargando cookies desde '{COOKIES_FILE}'...")
    driver.get(f"{BASE_URL}/slides")  # Ir a una página del dominio para establecer cookies

    with open(COOKIES_FILE, 'r') as f:
        cookies = json.load(f)

    for cookie in cookies:
        # Corrige el atributo sameSite si es necesario para compatibilidad
        if "sameSite" not in cookie or cookie["sameSite"] not in ["Strict", "Lax", "None"]:
            cookie["sameSite"] = "Lax"
        try:
            driver.add_cookie(cookie)
        except Exception as e:
            logger.error(f"Error al agregar la cookie '{cookie.get('name', 'N/A')}': {e}")

    logger.info("Cookies cargadas. Refrescando la página...")
    driver.refresh()


def scrape_course_structure(driver: uc.Chrome, course_url: str) -> List[Dict[str, Any]]:
    """Navega a la URL del curso y extrae su estructura (módulos y capítulos)."""
    logger.info("Obteniendo la estructura del curso...")
    driver.get(course_url)

    time.sleep(5)

    soup = BeautifulSoup(driver.page_source, 'html.parser')
    course_data = []

    module_categories = soup.find_all('li', class_=['o_wslides_slide_list_category', 'mt-4'])

    for category in module_categories:
        module_title_span = category.find('div', class_='o_wslides_slide_list_category_header').find('span', class_='text-muted')
        module_title = sanitize_name(module_title_span.get_text(strip=True)) if module_title_span else "Modulo Sin Titulo"

        chapters = []
        chapter_list = category.find('ul', class_='list-unstyled')
        if chapter_list:
            chapter_items = chapter_list.find_all('li', class_='o_wslides_slides_list_slide')
            for item in chapter_items:
                if 'o_not_editable' in item.get('class', []) or 'o_wslides_js_slides_list_empty' in item.get('class', []):
                    continue

                link_tag = item.find('a', class_='o_wslides_js_slides_list_slide_link')
                if link_tag and 'href' in link_tag.attrs:
                    chapter_title = sanitize_name(link_tag.find('span').get_text(strip=True))
                    chapter_url = BASE_URL + link_tag['href']
                    chapters.append({"title": chapter_title, "url": chapter_url})

        course_data.append({"module": module_title, "chapters": chapters})
        logger.info(f"Módulo encontrado: '{module_title}' con {len(chapters)} capítulos.")

    return course_data


def download_chapter_content(driver: uc.Chrome, chapter: Dict[str, str], module_path: Path, chapter_index: int):
    """Descarga el video y los recursos de un capítulo específico."""
    chapter_title = chapter['title']
    chapter_url = chapter['url']
    logger.info(f"Procesando capítulo: {chapter_title}")

    try:
        driver.get(chapter_url)

        time.sleep(5)

        soup = BeautifulSoup(driver.page_source, 'html.parser')

        # --- Búsqueda y descarga de video ---
        video_tag = soup.find('video', {'name': 'media'})
        source_tag = video_tag.find('source', type='video/mp4') if video_tag else None

        if source_tag and 'src' in source_tag.attrs:
            video_url = source_tag['src']
            logger.info("Video encontrado. Iniciando descarga...")

            video_filename = f"{chapter_index + 1:02d}-{chapter_title}"
            video_filename = split_name(video_filename, module_path)

            command = [
                "yt-dlp",
                "--add-headers", f"Referer: {BASE_URL}/",
                "--downloader", "aria2c",
                "-P", str(module_path),
                "-o", video_filename + ".%(ext)s",
                video_url
            ]
            subprocess.run(command, check=True)
            logger.info(f"Video '{chapter_title}' descargado exitosamente.")

        else:
            logger.warning("No se encontró video en este capítulo.")

            # --- Búsqueda y guardado de recursos ---
            resources = soup.find_all('a', class_='o_wslides_fs_slide_link')
            if resources:
                logger.info("Obteniendo recursos adicionales.")
                resource_filename = f"{chapter_index + 1:02d}-{chapter_title}_recursos.txt"
                resource_filepath = module_path / resource_filename

                with open(resource_filepath, 'w', encoding='utf-8') as f:
                    for item in resources:
                        resource_name = item.find('span').get_text(strip=True)
                        resource_link = item['href']
                        f.write(f"{resource_name}:\n{resource_link}\n\n")
                logger.info(f"Recursos guardados en '{resource_filename}'.")

    except subprocess.CalledProcessError as e:
        logger.error("Error al descargar el video con yt-dlp. Es posible que el video no esté disponible.")
        logger.error(f"Salida del comando: {e.stderr}")
    except Exception as e:
        logger.error(f"Ocurrió un error inesperado al procesar '{chapter_title}': {e}")


def main():
    """Función principal de todo el proceso."""
    course_url = input("Ingresa la URL del curso: ")
    if not course_url.startswith(BASE_URL):
        logger.error(f"La URL debe pertenecer a {BASE_URL}")
        return

    driver = create_driver()
    start_time = time.time()

    try:
        login_with_cookies(driver)

        course_data = scrape_course_structure(driver, course_url)
        if not course_data:
            logger.error("No se pudo extraer la estructura del curso.")
            return

        # Guardar estructura en JSON
        course_name_from_url = sanitize_name(urlparse(course_url).path.split('/')[-1])
        output_base_dir = Path(course_name_from_url)
        output_base_dir.mkdir(exist_ok=True)

        json_path = output_base_dir / f"{course_name_from_url}.json"
        with open(json_path, 'w', encoding='utf-8') as f:
            json.dump(course_data, f, ensure_ascii=False, indent=4)
        logger.info(f"Estructura del curso guardada en '{json_path}'")

        # Procesar y descargar contenido
        for mod_idx, module in enumerate(course_data):
            module_name = f"{mod_idx + 1:02d}-{module['module']}"
            module_path = output_base_dir / module_name
            module_path.mkdir(exist_ok=True)
            logger.info(f"Creando directorio para el módulo: '{module_path}'")

            for chap_idx, chapter in enumerate(module['chapters']):
                download_chapter_content(driver, chapter, module_path, chap_idx)
    finally:
        logger.info("Cerrando el navegador.")
        driver.quit()

    # Cálculo del tiempo total
    end_time = time.time()
    elapsed_time = end_time - start_time
    hours, rem = divmod(elapsed_time, 3600)
    minutes, seconds = divmod(rem, 60)
    logger.info(f"Proceso completado en {int(hours)}h, {int(minutes)}m y {int(seconds)}s.")
    print()


if __name__ == "__main__":
    main()
