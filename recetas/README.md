# Catálogo de recetas

Un fichero por receta. El agente y el skill `chef-compras` leen este índice para elegir recetas y abren solo las que necesitan.

## Índice

| Receta | Fichero | Etiquetas | Variantes |
|---|---|---|---|
| Cazuela mediterránea de pollo, tomates cherry, mozzarella y huevo en airfryer | [cazuela-mediterranea-pollo-airfryer.md](cazuela-mediterranea-pollo-airfryer.md) | mediterránea, hiperproteica, low carb, airfryer | original, fitness |

## Añadir una receta

1. Crear `recetas/<nombre-en-minusculas-con-guiones>.md`.
2. Empezar con la cabecera entre líneas `---`, una clave por línea:

   | Clave | Contenido |
   |---|---|
   | `nombre` | Nombre completo del plato |
   | `categoria` | desayuno, almuerzo, cena o merienda, separadas por comas |
   | `raciones` | Número entero de raciones de la ficha |
   | `etiquetas` | Separadas por comas |
   | `variantes` | Separadas por comas. Si solo hay una, `original` |
   | `alergenos` | Separados por comas, o `ninguno` |

   Son opcionales `dificultad`, `preparacion_min`, `coccion_min` y `equipamiento`.
3. Incluir estas secciones: `## Ingredientes` (tabla con una columna por variante, pesos en crudo por ración), `## Macros estimados por ración`, `## Preparación`, `## Alérgenos` y `## Conservación`.
4. Añadir una fila al índice de este fichero.
5. Ejecutar `.venv/bin/python -m pytest tests/test_recetas.py`.

Las pruebas comprueban la cabecera, las secciones, que la tabla de ingredientes tiene una columna por variante y que el índice y los ficheros coinciden.
