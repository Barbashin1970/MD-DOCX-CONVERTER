-- gost_captions.lua : автонумерация «Рисунок N — …» и «Таблица N — …»
-- Совместимо с pandoc 3.x. Проверено на pandoc 3.11.

local fig_n, tbl_n = 0, 0
local EMDASH = utf8.char(0x2014)

-- подпись как отдельный абзац со стилем Word
local function caption_para(style, inlines)
  return pandoc.Div({ pandoc.Para(inlines) },
                    pandoc.Attr("", {}, { ["custom-style"] = style }))
end

-- «Таблица 3 — Название»
local function numbered(word, n, rest)
  local out = { pandoc.Str(word), pandoc.Space(), pandoc.Str(tostring(n)) }
  if rest and #rest > 0 then
    table.insert(out, pandoc.Space())
    table.insert(out, pandoc.Str(EMDASH))
    table.insert(out, pandoc.Space())
    for _, i in ipairs(rest) do table.insert(out, i) end
  end
  return out
end

-- убрать ведущее «Таблица»/«Рисунок» (+ необязательное «N» и тире) из подписи
local function strip_prefix(inlines, word)
  local ils = pandoc.List(inlines)
  if #ils > 0 and ils[1].t == "Str" and ils[1].text == word then
    ils:remove(1)                                  -- слово
    while #ils > 0 and ils[1].t == "Space" do ils:remove(1) end
    if #ils > 0 and ils[1].t == "Str" and ils[1].text:match("^%d+$") then
      ils:remove(1)
      while #ils > 0 and ils[1].t == "Space" do ils:remove(1) end
    end
    if #ils > 0 and ils[1].t == "Str"
       and (ils[1].text == EMDASH or ils[1].text == "-" or ils[1].text == "--"
            or ils[1].text == ":" or ils[1].text == EMDASH .. "") then
      ils:remove(1)
      while #ils > 0 and ils[1].t == "Space" do ils:remove(1) end
    end
  end
  return ils
end

-- Абзац, состоящий только из картинки -> картинка + подпись «Рисунок N — alt»
local function figure_from_para(blk)
  -- pandoc 3 + implicit_figures даёт блок Figure
  if blk.t == "Figure" then
    fig_n = fig_n + 1
    local cap = strip_prefix(pandoc.utils.blocks_to_inlines(blk.caption.long or {}), "Рисунок")
    return { pandoc.Div(blk.content, pandoc.Attr("", {}, { ["custom-style"] = "Figure" })),
             caption_para("Image Caption", numbered("Рисунок", fig_n, cap)) }
  end
  if blk.t ~= "Para" then return nil end
  local ils = blk.content
  if #ils ~= 1 or ils[1].t ~= "Image" then return nil end
  local img = ils[1]
  fig_n = fig_n + 1
  local cap = strip_prefix(img.caption, "Рисунок")
  local body = pandoc.Div({ pandoc.Para({ img }) },
                          pandoc.Attr("", {}, { ["custom-style"] = "Figure" }))
  return { body, caption_para("Image Caption", numbered("Рисунок", fig_n, cap)) }
end

function Pandoc(doc)
  local out = pandoc.List({})
  local blocks = doc.blocks
  local i = 1
  while i <= #blocks do
    local b = blocks[i]

    -- 1) подпись таблицы: абзац «Таблица …», сразу за которым идёт таблица
    if b.t == "Para" and blocks[i+1] and blocks[i+1].t == "Table"
       and #b.content > 0 then
      local flat = pandoc.utils.stringify(b.content)
      if flat:match("^%s*Таблица") then
        tbl_n = tbl_n + 1
        local inner = b.content
        -- снять внешний Strong/Emph, если подпись выделена для GitHub
        if #inner == 1 and (inner[1].t == "Strong" or inner[1].t == "Emph") then
          inner = inner[1].content
        end
        local cap = strip_prefix(inner, "Таблица")
        out:insert(caption_para("Table Caption", numbered("Таблица", tbl_n, cap)))
        i = i + 1
        goto continue
      end
    end

    -- 2) рисунок
    do
      local fig = figure_from_para(b)
      if fig then
        for _, x in ipairs(fig) do out:insert(x) end
        i = i + 1
        goto continue
      end
    end

    out:insert(b)
    i = i + 1
    ::continue::
  end
  return pandoc.Pandoc(out, doc.meta)
end
