# validator 서버 — formalizer(LLM 형식화) + checker(z3) 를 묶은 HTTP API
#   docker build -t validator . && docker run -p 8000:7860 validator
#   docker run -e ANTHROPIC_API_KEY=sk-ant-... -p 8000:7860 validator     # anthropic provider 사용 시
FROM python:3.12-slim
RUN useradd -m -u 1000 user
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY checker.py server.py ./
COPY formalizer ./formalizer
USER user
ENV PORT=7860
EXPOSE 7860
CMD ["python", "server.py"]
