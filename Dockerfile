FROM docker.m.daocloud.io/library/python:3.11-slim

ENV TZ=Asia/Shanghai
RUN ln -sf /usr/share/zoneinfo/Asia/Shanghai /etc/localtime

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -i https://pypi.tuna.tsinghua.edu.cn/simple -r requirements.txt || \
    pip install --no-cache-dir -r requirements.txt

COPY app/ ./app/
CMD ["python", "-m", "app.main"]
