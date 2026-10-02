FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 TZ=Europe/Zurich
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt \
 && playwright install --with-deps chromium
COPY searchlight ./searchlight

# Mount a folder holding config.yaml (with `data_dir: /data`) and, if you use
# Facebook, the session.json written by `searchlight login` on your laptop.
VOLUME /data
ENTRYPOINT ["python", "-m", "searchlight", "-c", "/data/config.yaml"]
CMD ["watch"]
