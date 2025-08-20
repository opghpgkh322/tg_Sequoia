# Используем официальный образ Python
FROM python:3.13-slim

# Установим необходимые зависимости
WORKDIR /app

# Копируем файлы проекта в контейнер
COPY . /app/

# Устанавливаем зависимости
RUN pip install --no-cache-dir -r requirements.txt

# Команда для запуска бота
CMD ["python", "main.py"]