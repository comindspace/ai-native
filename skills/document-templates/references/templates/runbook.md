# Runbook: [Название сервиса]

**Версия:** 1.0
**Дата:** YYYY-MM-DD
**Автор:** [имя]

## Обзор

| Параметр | Значение |
|----------|----------|
| Сервис | [название] |
| Репозиторий | [ссылка на GitLab] |
| Wiki (Source of Truth) | [ссылка на Yonote: `Runbooks/<service>`] |
| Staging | https://staging.example.com |
| Production | https://example.com |

## Архитектура

```
┌─────────┐     ┌─────────┐     ┌─────────┐
│ Nginx   │────▶│ Backend │────▶│   DB    │
│         │     │ (FastAPI)     │(Postgres)
└─────────┘     └─────────┘     └─────────┘
      │               │
      ▼               ▼
┌─────────┐     ┌─────────┐
│Frontend │     │  Redis  │
│ (React) │     │         │
└─────────┘     └─────────┘
```

## Зависимости

| Сервис | Порт | Назначение |
|--------|------|------------|
| Backend | 8000 | API |
| Frontend | 80/443 | Web UI |
| PostgreSQL | 5432 | База данных |
| Redis | 6379 | Кэш/очереди |

## Конфигурация

### Переменные окружения

| Переменная | Описание | Пример |
|------------|----------|--------|
| DATABASE_URL | Подключение к БД | postgresql://user:pass@host:5432/db |
| REDIS_URL | Подключение к Redis | redis://host:6379 |
| SECRET_KEY | Секретный ключ | [сгенерировать] |
| DEBUG | Режим отладки | false |

### Расположение конфигов

- `/app/deploy/env/backend.env`
- `/app/deploy/env/frontend.env`
- `/app/deploy/docker-compose.yml`

## Операции

### Запуск

```bash
cd /app/deploy
docker-compose up -d
```

### Остановка

```bash
cd /app/deploy
docker-compose down
```

### Рестарт

```bash
cd /app/deploy
docker-compose restart backend
```

### Просмотр логов

```bash
# Все сервисы
docker-compose logs -f --tail=100

# Конкретный сервис
docker-compose logs -f --tail=100 backend
```

### Обновление

```bash
cd /app
git pull origin main
docker-compose pull
docker-compose up -d
```

### Миграции БД

```bash
docker-compose exec backend alembic upgrade head
```

### Откат миграции

```bash
docker-compose exec backend alembic downgrade -1
```

## Health Checks

### Backend

```bash
curl -f http://localhost:8000/health
# Ожидаемый ответ: {"status": "ok"}
```

### База данных

```bash
docker-compose exec db pg_isready -U postgres
```

### Redis

```bash
docker-compose exec redis redis-cli ping
# Ожидаемый ответ: PONG
```

## Мониторинг

### Метрики

- CPU/Memory: [ссылка на Grafana или htop]
- Запросы/сек: [ссылка]
- Ошибки: [ссылка]

### Алерты

| Алерт | Условие | Действие |
|-------|---------|----------|
| High CPU | > 80% 5 мин | Проверить нагрузку |
| High Memory | > 90% | Проверить утечки |
| 5xx errors | > 10/мин | Проверить логи |

## Типичные проблемы

### Проблема: 502 Bad Gateway

**Симптомы:** Nginx возвращает 502

**Причина:** Backend не запущен или упал

**Решение:**
```bash
docker-compose logs backend
docker-compose restart backend
```

### Проблема: Медленные запросы

**Симптомы:** Latency > 1s

**Причина:** Нагрузка на БД или отсутствие индексов

**Решение:**
1. Проверить slow query log
2. Добавить индексы
3. Проверить Redis (кэш работает?)

### Проблема: Нет места на диске

**Симптомы:** Ошибки записи, контейнеры падают

**Решение:**
```bash
# Проверить место
df -h

# Очистить Docker
docker system prune -a
```

## Бэкапы

### База данных

```bash
# Создать бэкап
docker-compose exec db pg_dump -U postgres dbname > backup.sql

# Восстановить
cat backup.sql | docker-compose exec -T db psql -U postgres dbname
```

### Расписание

- Ежедневно: 03:00 UTC
- Хранение: 7 дней

## Контакты

| Роль | Имя | Контакт |
|------|-----|---------|
| DevOps | [имя] | [telegram/email] |
| Tech Lead | [имя] | [telegram/email] |
| PM | [имя] | [telegram/email] |
