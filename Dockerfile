FROM mcr.microsoft.com/playwright/python:v1.44.0-jammy

# Set up user for Hugging Face
RUN useradd -m -u 1000 user
USER user
ENV PATH="/home/user/.local/bin:${PATH}"
WORKDIR /home/user/app

# Install requirements
COPY --chown=user requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
RUN playwright install chromium

# Copy your scrape.py and the session folders
COPY --chown=user . .

# Expose Port for HF
EXPOSE 7860

# Use the correct filename (scrape.py)
CMD ["streamlit", "run", "final_scrape.py", "--server.port=7860", "--server.address=0.0.0.0"]