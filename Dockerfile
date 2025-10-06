# Use Python 3.13 slim image
FROM python:alpine

# Set working directory
WORKDIR /app

# Install system dependencies including FFmpeg
RUN apk add --no-cache ffmpeg git

# Copy requirements first for better caching
COPY requirements.txt .

# Install Python dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY . .

# Create non-root user for security
RUN adduser -D -h /home/musicbot musicbot && \
    chown -R musicbot:musicbot /app
USER musicbot

# Expose port (not needed for Discord bot but good practice)
EXPOSE 8080

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD python -c "import sys; sys.exit(0)"

# Run the bot
CMD ["python", "bot.py"]