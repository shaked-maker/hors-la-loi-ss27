-- Hors La Loi SS27 — Supabase Schema
-- Run this in Supabase Dashboard → SQL Editor

CREATE TABLE IF NOT EXISTS public.garments (
  id            UUID        DEFAULT gen_random_uuid() PRIMARY KEY,
  collection    TEXT        NOT NULL,           -- 'femme' | 'homme'
  filename      TEXT        NOT NULL UNIQUE,    -- 'Artboard 2@3x-100.jpg'
  model_code    TEXT        DEFAULT '',
  prompt        TEXT        DEFAULT '',
  cad_image_url TEXT        DEFAULT '',         -- Supabase Storage public URL
  result_url    TEXT        DEFAULT '',         -- Supabase Storage public URL
  created_at    TIMESTAMPTZ DEFAULT NOW(),
  updated_at    TIMESTAMPTZ DEFAULT NOW()
);

-- Enable Row Level Security
ALTER TABLE public.garments ENABLE ROW LEVEL SECURITY;

-- Allow all operations (development — restrict before going to production)
CREATE POLICY "public_all" ON public.garments
  FOR ALL USING (true) WITH CHECK (true);
