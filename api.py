from rag import *
import logging
import sys, os
# Ensure Backend is on path for utils
sys.path.append(os.path.join(os.path.dirname(__file__), '..'))
from utils.logging_config import configure_logging
logger = configure_logging("api_data")
from dotenv import load_dotenv
import uvicorn
import requests
import os
import asyncio
from llm_service import llm_service
from datetime import datetime
from subject_data import subjects_data
from lectures_data import lectures_data
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
# Test data for fallback when database is empty
test_data = [
    {
        "id": 1,
        "title": "Sample Test",
        "subject": "Mathematics",
        "questions": [
            {
                "question": "What is 2 + 2?",
                "options": ["3", "4", "5", "6"],
                "correct_answer": "4"
            }
        ]
    }
]
from db import pdf_collection , image_collection, user_collection
from datetime import datetime, timezone
import shutil
import time
try:
    from docx import Document
    import docx2txt
    DOCX_AVAILABLE = True
except ImportError:
    DOCX_AVAILABLE = False
    print("⚠️ python-docx not available. DOC/DOCX support will be limited.")

# Load environment variables from centralized configuration
import sys
sys.path.append(os.path.join(os.path.dirname(__file__), '..'))
from shared_config import load_shared_config

# Load centralized configuration
load_shared_config("api_data")

# Create temporary directory for file processing
TEMP_DIR = os.path.join(os.path.dirname(__file__), "temp")
os.makedirs(TEMP_DIR, exist_ok=True)

from fastapi import FastAPI, UploadFile, File, HTTPException
from pydantic import BaseModel
from typing import List, Optional
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse, JSONResponse
from uuid import uuid4

# Initialize FastAPI app
app = FastAPI()

_allowed = os.getenv("ALLOWED_ORIGINS", "").strip()
_allowed_list = [o.strip() for o in _allowed.split(",") if o.strip()] or [
    "http://localhost",
    "http://localhost:3000",
    "http://localhost:5173",
]
app.add_middleware(
    CORSMiddleware,
    allow_origins=_allowed_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Global exception handler for consistent errors
@app.exception_handler(Exception)
async def _on_error(request, exc):
    trace = str(uuid4())
    logger.exception(f"[{trace}] Unhandled error: {exc}")
    return JSONResponse(status_code=500, content={"error": {"code": "INTERNAL_ERROR", "message": "Unexpected error"}, "trace_id": trace})

# Add a health check endpoint
@app.get("/health")
def health_check():
    return {"status": "ok"}

# ==== Subject API Models and Routes ====
class Subject(BaseModel):
    id: int
    name: str
    code: str

@app.get("/subjects_dummy")
def get_subjects():
    return JSONResponse(content=subjects_data)


# ==== Lectures API Models and Routes ====
class Lecture(BaseModel):
    id: int
    topic: str
    subject_id: int

@app.get("/lecture_dummy")
def get_lectures():
    return JSONResponse(content=lectures_data)

# ==== Test API Models and Routes ====
class Test(BaseModel):
    id: int
    name: str
    subject_id: int
    date: Optional[str] = None


@app.get("/test_dummy")
def get_test():
    return JSONResponse(content=test_data)

#Chatbot
groq_api_key = os.environ.get('GROQ_API_KEY')

# Temporary in-memory storage
user_queries: List[dict] = []
llm_responses: List[dict] = []

# Pydantic model for request validation
class ChatMessage(BaseModel):
    message: str
    llm: str = "grok"  # Default to grok, accepts: grok, llama, chatgpt, uniguru
    timestamp: str = None
    type: str = "chat_message"


# Route 1: Receive query from frontend
@app.post("/chatpost")
async def receive_query(chat: ChatMessage):
    timestamp = datetime.now(timezone.utc).isoformat().replace('+00:00','Z')
    query_record = {
        "message": chat.message,
        "llm_model": chat.llm,  # Store the selected model
        "timestamp": timestamp,
        "type": "chat_message"
    }
    try:
        chat_collection = user_collection.insert_one(query_record)
        query_record["_id"] = str(chat_collection.inserted_id)  # Add the MongoDB ID to the record
        print(f"Received message: {chat.message} (Model: {chat.llm})")
        return {"status": "Query received", "data": query_record}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to store query:{str(e)}")


import requests

def parse_word_document(file_path: str) -> dict:
    """Parse Word document (DOC/DOCX) and extract text content"""
    try:
        if not DOCX_AVAILABLE:
            raise Exception("python-docx library not available")

        # Extract text from DOCX file
        if file_path.lower().endswith('.docx'):
            # Method 1: Using python-docx for structured parsing
            try:
                doc = Document(file_path)
                paragraphs = []
                for paragraph in doc.paragraphs:
                    if paragraph.text.strip():
                        paragraphs.append(paragraph.text.strip())

                raw_text = '\n'.join(paragraphs)

                # If no content found, try docx2txt as fallback
                if not raw_text.strip():
                    raw_text = docx2txt.process(file_path)

            except Exception:
                # Fallback to docx2txt
                raw_text = docx2txt.process(file_path)
        else:
            # For .doc files, we'll need a different approach
            # For now, return an error message
            raise Exception("DOC files are not fully supported. Please convert to DOCX format.")

        if not raw_text.strip():
            return {"title": "", "body": "", "sections": []}

        # Extract title (first non-empty line)
        lines = raw_text.strip().split('\n')
        title = next((line.strip() for line in lines if line.strip()), "")

        # Simple section detection (lines that look like headings)
        sections = []
        current_section = {"heading": "Content", "content": ""}

        for line in lines:
            line = line.strip()
            if not line:
                continue

            # Simple heuristic for section headings (short lines, possibly numbered)
            if (len(line) < 100 and
                (line.isupper() or
                 any(line.startswith(prefix) for prefix in ['1.', '2.', '3.', '4.', '5.', 'Chapter', 'Section']) or
                 line.endswith(':'))):
                # Save previous section if it has content
                if current_section["content"].strip():
                    sections.append(current_section)
                # Start new section
                current_section = {"heading": line, "content": ""}
            else:
                current_section["content"] += line + "\n"

        # Add the last section
        if current_section["content"].strip():
            sections.append(current_section)

        # If no sections were detected, put everything in one section
        if not sections:
            sections = [{"heading": "Document Content", "content": raw_text}]

        return {
            "title": title,
            "body": raw_text,
            "sections": sections
        }

    except Exception as e:
        print(f"Error parsing Word document: {e}")
        return {"title": "", "body": f"Error parsing document: {str(e)}", "sections": []}

def call_llm(prompt: str, llm: str) -> str:
    """
    Call the specified LLM API with the given prompt.
    """
    groq_api_key = os.environ.get('GROQ_API_KEY')
    openai_api_key = os.environ.get('OPENAI_API_KEY')

    try:
        if llm == "grok":
            # Use Groq API with Gemma2 model for "grok" to differentiate from llama
            headers = {
                "Authorization": f"Bearer {groq_api_key}",
                "Content-Type": "application/json"
            }
            # Add a system message to make Grok responses more distinctive
            payload = {
                "model": "gemma2-9b-it",  # Using Gemma2 model for "grok" instead of LLaMA
                "messages": [
                    {"role": "user", "content": f"You are Grok, an AI assistant with a witty, direct, and slightly irreverent personality. You provide helpful answers but with a touch of humor and candor. {prompt}"}
                ],
                "temperature": 0.8,  # Slightly higher temperature for more creative responses
                "max_tokens": 512,
                "top_p": 1.0
            }

            response = requests.post(
                "https://api.groq.com/openai/v1/chat/completions",
                headers=headers,
                json=payload,
                timeout=30
            )
            response.raise_for_status()
            result = response.json()
            return result['choices'][0]['message']['content'].strip()

        elif llm == "llama":
            # Use Groq API with larger LLaMA model
            headers = {
                "Authorization": f"Bearer {groq_api_key}",
                "Content-Type": "application/json"
            }
            # Add a system message to make LLaMA responses more distinctive
            payload = {
                "model": "llama3-70b-8192",  # Larger LLaMA model
                "messages": [
                    {"role": "system", "content": "You are LLaMA, a helpful, harmless, and honest AI assistant. You provide detailed, thoughtful responses with a focus on being educational and comprehensive."},
                    {"role": "user", "content": prompt}
                ],
                "temperature": 0.6,  # Lower temperature for more consistent responses
                "max_tokens": 512,
                "top_p": 1.0
            }

            response = requests.post(
                "https://api.groq.com/openai/v1/chat/completions",
                headers=headers,
                json=payload,
                timeout=30
            )
            response.raise_for_status()
            result = response.json()
            return result['choices'][0]['message']['content'].strip()

        elif llm == "chatgpt":
            # Use Groq API with LLaMA 3.1 model as ChatGPT alternative
            headers = {
                "Authorization": f"Bearer {groq_api_key}",
                "Content-Type": "application/json"
            }
            payload = {
                "model": "llama-3.1-8b-instant",  # Using LLaMA 3.1 for ChatGPT
                "messages": [
                    {"role": "system", "content": "You are ChatGPT, a helpful AI assistant created by OpenAI. You provide clear, accurate, and helpful responses."},
                    {"role": "user", "content": prompt}
                ],
                "temperature": 0.7,
                "max_tokens": 512
            }

            response = requests.post(
                "https://api.groq.com/openai/v1/chat/completions",
                headers=headers,
                json=payload,
                timeout=30
            )
            response.raise_for_status()
            result = response.json()
            return result['choices'][0]['message']['content'].strip()

        elif llm == "uniguru":
            # UniGuru API (Llama model) via ngrok
            uniguru_url = os.getenv("UNIGURU_NGROK_ENDPOINT", "https://3a46c48e4d91.ngrok-free.app") + "/v1/chat/completions"
            headers = {
                "Content-Type": "application/json",
                "ngrok-skip-browser-warning": "true"
            }
            data = {
                "model": "llama3.1",
                "messages": [
                    {"role": "user", "content": prompt}
                ],
                "max_tokens": 2048,
                "temperature": 0.7
            }

            response = requests.post(uniguru_url, headers=headers, json=data, timeout=60)
            response.raise_for_status()
            result = response.json()
            return result['choices'][0]['message']['content'].strip()

        else:
            # Default fallback
            response = llm_service.generate_response(prompt)
            return response

    except requests.exceptions.RequestException as e:
        print(f"❌ Error calling {llm} API: {e}")
        return f"I apologize, but I'm experiencing technical difficulties with the {llm} model right now. Please try again in a few moments."
    except Exception as e:
        print(f"❌ Unexpected error with {llm}: {e}")
        return "I apologize, but I'm experiencing technical difficulties right now. Please try again in a few moments."

def call_groq_llama3(prompt: str) -> str:
    """Legacy function - now redirects to call_llm with grok model"""
    return call_llm(prompt, "grok")


# Route 2: Send LLM response back
@app.get("/chatbot")
async def send_response():
    try:
        # Fetch the latest query from MongoDB
        latest_query = user_collection.find_one({"type": "chat_message", "response":None}, sort=[("timestamp", -1)])
        if not latest_query:
            return {"error": "No queries yet"}

        query_message = latest_query["message"]
        selected_model = latest_query.get("llm_model", "grok")  # Get the selected model, default to grok
        print(f"Processing query: {query_message} (Model: {selected_model})")

        # Use the selected model
        llm_reply = call_llm(query_message, selected_model)

        timestamp = datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z')
        response_data = {
            "message": llm_reply,
            "model_used": selected_model,  # Include which model was used
            "timestamp": timestamp,
            "type": "chat_response",
            "query_id": str(latest_query["_id"])  # Link response to query
        }

        user_collection.update_one(
            {"_id": latest_query["_id"]},
            {"$set": {"response": response_data}}
        )

        return {
            "_id": str(latest_query["_id"]),
            "query": query_message,
            "response": response_data
        }

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to process response:{str(e)}")

@app.post("/process-pdf", response_model=PDFResponse)
async def process_pdf(file: UploadFile = File(...), llm: str = "grok"):
    temp_file_path = ""
    try:
        # Check file extension and validate supported formats
        file_ext = file.filename.lower().split('.')[-1] if '.' in file.filename else ''
        supported_formats = ['pdf', 'doc', 'docx']

        if file_ext not in supported_formats:
            raise HTTPException(status_code=400, detail="Only PDF, DOC, and DOCX files are allowed")

        # Create temp file with appropriate extension
        temp_file_path = os.path.join(TEMP_DIR, f"temp_document_{time.strftime('%Y%m%d_%H%M%S')}.{file_ext}")
        with open(temp_file_path, "wb") as temp_file:
            shutil.copyfileobj(file.file, temp_file)

        # Parse document based on file type
        if file_ext == 'pdf':
            structured_data = parse_pdf(temp_file_path)
        elif file_ext in ['doc', 'docx']:
            structured_data = parse_word_document(temp_file_path)

        if not structured_data["body"]:
            raise HTTPException(status_code=400, detail="Failed to parse document content")

        # Create a comprehensive prompt for document summarization
        document_content = structured_data["body"]
        prompt = f"""Please provide a detailed summary of the following document in a clean, well-structured format:

Title: {structured_data.get('title', 'Document')}

Content:
{document_content}

Please provide a comprehensive summary with the following structure:

Overview
Provide a brief overview of the document's main purpose and scope.

Key Points
• List the main topics and important concepts covered
• Highlight significant findings or arguments
• Include relevant data, statistics, or examples

Important Details
• Explain crucial information that readers should understand
• Clarify any complex concepts or terminology
• Mention important dates, names, or references

Conclusions & Insights
• Summarize the main conclusions or outcomes
• Provide actionable insights or recommendations
• Explain the significance or implications of the content

IMPORTANT: Format your response with clear sections and bullet points for easy reading. Do NOT use markdown formatting like ** or * symbols. Use plain text with clear section headers. Make it comprehensive yet concise, focusing on the most valuable information."""

        # Use the selected LLM model for summarization
        answer = call_llm(prompt, llm)

        audio_file = text_to_speech(answer, file_prefix="output_pdf")
        audio_url = f"/api/stream/{os.path.basename(audio_file)}" if audio_file else "No audio generated"

        # Store to MongoDB
        pdf_doc = {
            "filename": file.filename,
            "file_type": file_ext,
            "title": structured_data["title"],
            "sections": [{"heading": s["heading"], "content": s["content"]} for s in structured_data["sections"]],
            "summary": answer,
            "llm_model": llm,
            "audio_file": audio_url,
            "timestamp": datetime.now(timezone.utc)
        }
        pdf_collection.insert_one(pdf_doc)

        global pdf_response
        pdf_response = PDFResponse(
            title=structured_data["title"],
            sections=[Section(heading=s["heading"], content=s["content"]) for s in structured_data["sections"]],
            query=f"Document summary using {llm.upper()} model",
            answer=answer,
            audio_file=audio_url,
            llm=llm
        )
        return pdf_response

    except Exception as e:
        logger.error(f"Error processing document: {e}")
        raise HTTPException(status_code=500, detail=str(e))

    finally:
        if temp_file_path and os.path.exists(temp_file_path):
            os.remove(temp_file_path)


@app.post("/process-img", response_model=ImageResponse)
async def process_image(file: UploadFile = File(...), llm: str = "grok"):
    temp_image_path = ""
    try:
        if not file.filename.lower().endswith((".jpg", ".jpeg", ".png")):
            raise HTTPException(status_code=400, detail="Only JPG, JPEG, or PNG files are allowed")

        temp_image_path = os.path.join(
            TEMP_DIR,
            f"temp_image_{time.strftime('%Y%m%d_%H%M%S')}{os.path.splitext(file.filename)[1]}"
        )

        with open(temp_image_path, "wb") as temp_file:
            shutil.copyfileobj(file.file, temp_file)

        ocr_text = extract_text_easyocr(temp_image_path).strip()
        logger.info(f"OCR raw output: {repr(ocr_text)}")

        if not ocr_text:
            ocr_text = "No readable text found in the image."
            answer = "This image does not contain any readable text that can be extracted and summarized."
            query = "Image analysis"
        else:
            # Create a comprehensive prompt for image text analysis
            prompt = f"""Please analyze and summarize the following text extracted from an image:

Extracted Text:
{ocr_text}

Please provide:
1. A summary of what the text contains
2. Key information and main points
3. Context or purpose of the text (if apparent)
4. Any important details or insights

Make the analysis comprehensive and helpful."""

            # Use the selected LLM model for analysis
            answer = call_llm(prompt, llm)
            query = f"Image text analysis using {llm.upper()} model"

        audio_file = text_to_speech(answer, file_prefix="output_image")
        audio_url = f"/api/stream/{os.path.basename(audio_file)}" if audio_file else "No audio generated"

        # Store to MongoDB
        image_doc = {
            "filename": file.filename,
            "ocr_text": ocr_text,
            "query": query,
            "answer": answer,
            "llm_model": llm,
            "audio_file": audio_url,
            "timestamp": datetime.now(timezone.utc)
        }
        image_collection.insert_one(image_doc)

        global image_response
        image_response = ImageResponse(
            ocr_text=ocr_text,
            query=query,
            answer=answer,
            audio_file=audio_url,
            llm=llm
        )
        return image_response

    except Exception as e:
        logger.error(f"Error processing image: {e}")
        raise HTTPException(status_code=500, detail=str(e))

    finally:
        if temp_image_path and os.path.exists(temp_image_path):
            os.remove(temp_image_path)

@app.get("/summarize-pdf", response_model=PDFResponse)
async def summarize_pdf():
    if pdf_response is None:
        raise HTTPException(status_code=404, detail="No PDF has been processed yet.")
    return pdf_response

@app.get("/summarize-img", response_model=ImageResponse)
async def summarize_image():
    if image_response is None:
        raise HTTPException(status_code=404, detail="No image has been processed yet.")
    return image_response

@app.get("/api/stream/{filename}")
async def stream_audio(filename: str):
    audio_path = os.path.join(TEMP_DIR, filename)

    if not os.path.exists(audio_path):
        raise HTTPException(status_code=404, detail="Audio file not found")

    return FileResponse(
        path=audio_path,
        media_type="audio/mpeg",
        filename=filename
    )

@app.get("/api/audio/{filename}")
async def download_audio(filename: str):
    audio_path = os.path.join(TEMP_DIR, filename)

    if not os.path.exists(audio_path):
        raise HTTPException(status_code=404, detail="Audio file not found")

    return FileResponse(
        path=audio_path,
        media_type="audio/mpeg",
        filename=filename
    )

@app.get("/process-pdf-stream")
async def process_pdf_stream(
    file_path: str = None,
    llm: str = "uniguru"
):
    """
    Stream PDF processing results line by line for live rendering
    """
    async def generate_content():
        try:
            yield f"data: 🔍 Starting document analysis...\n\n"
            await asyncio.sleep(0.1)

            # Get the latest PDF response
            if pdf_response is None:
                yield f"data: ❌ No PDF has been processed yet. Please upload a document first.\n\n"
                yield f"data: [ERROR]\n\n"
                return

            yield f"data: 📄 Processing: {pdf_response.title}\n\n"
            await asyncio.sleep(0.2)

            yield f"data: 🤖 Using UNIGURU AI model\n\n"
            await asyncio.sleep(0.2)

            yield f"data: 📝 Generating comprehensive summary...\n\n"
            await asyncio.sleep(0.3)

            # Clean the answer content (remove markdown formatting)
            answer = pdf_response.answer

            # Remove markdown formatting
            cleaned_answer = answer.replace('**', '').replace('*', '').replace('##', '').replace('#', '')

            # Split content into lines for streaming
            content_lines = cleaned_answer.split('\n')

            yield f"data: \n\n"
            yield f"data: {pdf_response.title}\n\n"
            yield f"data: \n\n"

            # Stream content line by line
            for i, line in enumerate(content_lines):
                if line.strip():  # Only send non-empty lines
                    yield f"data: {line.strip()}\n\n"
                    await asyncio.sleep(0.05)  # Small delay for live rendering effect
                else:
                    yield f"data: \n\n"  # Send empty line
                    await asyncio.sleep(0.02)

            yield f"data: \n\n"
            yield f"data: ✅ Document analysis complete!\n\n"
            yield f"data: 🎵 Audio summary available for download\n\n"
            yield f"data: [END]\n\n"

        except Exception as e:
            yield f"data: ❌ Error during streaming: {str(e)}\n\n"
            yield f"data: [ERROR]\n\n"

    return StreamingResponse(
        generate_content(),
        media_type="text/plain",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "Content-Type": "text/plain; charset=utf-8"
        }
    )

@app.get("/process-img-stream")
async def process_img_stream(
    file_path: str = None,
    llm: str = "uniguru"
):
    """
    Stream image processing results line by line for live rendering
    """
    async def generate_content():
        try:
            yield f"data: 🔍 Starting image analysis...\n\n"
            await asyncio.sleep(0.1)

            # Get the latest image response
            if image_response is None:
                yield f"data: ❌ No image has been processed yet. Please upload an image first.\n\n"
                yield f"data: [ERROR]\n\n"
                return

            yield f"data: 🖼️ Processing image with OCR...\n\n"
            await asyncio.sleep(0.2)

            yield f"data: 🤖 Using UNIGURU AI model\n\n"
            await asyncio.sleep(0.2)

            yield f"data: 📝 Generating comprehensive image analysis...\n\n"
            await asyncio.sleep(0.3)

            # Check if OCR text was found
            if image_response.ocr_text and image_response.ocr_text != "No readable text found in the image.":
                yield f"data: 📖 Text extracted from image:\n\n"
                yield f"data: {image_response.ocr_text}\n\n"
                yield f"data: \n\n"

            # Clean the answer content (remove markdown formatting)
            answer = image_response.answer

            # Remove markdown formatting
            cleaned_answer = answer.replace('**', '').replace('*', '').replace('##', '').replace('#', '')

            # Split content into lines for streaming
            content_lines = cleaned_answer.split('\n')

            yield f"data: 📊 Analysis Results:\n\n"
            yield f"data: \n\n"

            # Stream content line by line
            for i, line in enumerate(content_lines):
                if line.strip():  # Only send non-empty lines
                    yield f"data: {line.strip()}\n\n"
                    await asyncio.sleep(0.05)  # Small delay for live rendering effect
                else:
                    yield f"data: \n\n"  # Send empty line
                    await asyncio.sleep(0.02)

            yield f"data: \n\n"
            yield f"data: ✅ Image analysis complete!\n\n"
            yield f"data: 🎵 Audio summary available for download\n\n"
            yield f"data: [END]\n\n"

        except Exception as e:
            yield f"data: ❌ Error during streaming: {str(e)}\n\n"
            yield f"data: [ERROR]\n\n"

    return StreamingResponse(
        generate_content(),
        media_type="text/plain",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "Content-Type": "text/plain; charset=utf-8"
        }
    )

if __name__ == "__main__":
    try:
        # Use port 8001 to avoid conflict with main server on port 8000
        uvicorn.run(app, host="127.0.0.1", port=8001)
    except Exception as e:
        logger.error(f"Failed to start server: {e}")
        raise



