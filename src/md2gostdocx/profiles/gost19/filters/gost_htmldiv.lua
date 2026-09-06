-- <div class="requirement"> ... </div> из GFM -> Div с custom-style Word.
-- На GitHub такой блок рендерится обычным текстом (теги скрыты), в DOCX
-- получает стиль абзаца из reference.docx.
--
-- Требование к разметке: пустая строка после открывающего тега и перед
-- закрывающим. Иначе pandoc складывает всё в один RawBlock, и содержимое
-- внутрь Div уже не попадёт.
--
-- Фильтр обязан быть устойчив к ошибкам разметки: незакрытый <div> раньше
-- уносил с собой весь остаток документа молча.

local MAP = { requirement = "Requirement", note = "Note",
              warning = "Warning", term = "Term",
              tip = "Tip", important = "Important", caution = "Caution",
              ["requirements-table"] = "RequirementsTable",
              ["terms-table"] = "TermsTable" }

local function warn(message)
  if pandoc.log and pandoc.log.warn then
    pandoc.log.warn(message)
  else
    io.stderr:write("[WARNING] " .. message .. "\n")
  end
end

-- Открывающий тег: и "..." и '...'. Возвращает класс только если в блоке
-- ВСЁ, что есть, — это сам тег: иначе содержимое склеено с ним и потерялось бы.
local function opening_class(text)
  local rest = text:match('^%s*<div%s+class%s*=%s*"([%w_%-]+)"%s*>%s*$')
             or text:match("^%s*<div%s+class%s*=%s*'([%w_%-]+)'%s*>%s*$")
  return rest
end

local function looks_like_open(text)
  return text:match("^%s*<div[%s>]") ~= nil
end

function Pandoc(doc)
  local out, stack = pandoc.List({}), {}

  local function sink(block)
    if #stack > 0 then
      stack[#stack].blocks:insert(block)
    else
      out:insert(block)
    end
  end

  local function close_top()
    local top = table.remove(stack)
    local style = MAP[top.class] or top.class
    sink(pandoc.Div(top.blocks, pandoc.Attr("", {}, { ["custom-style"] = style })))
  end

  for _, block in ipairs(doc.blocks) do
    if block.t == "RawBlock" and block.format == "html" then
      local class = opening_class(block.text)
      if class then
        stack[#stack + 1] = { class = class, blocks = pandoc.List({}) }
      elseif block.text:match("^%s*</div>%s*$") then
        if #stack > 0 then
          close_top()
        else
          warn("gost_htmldiv: закрывающий </div> без открывающего — пропущен")
        end
      elseif looks_like_open(block.text) then
        -- Тег склеен с содержимым: без пустой строки после него pandoc
        -- кладёт весь блок в один RawBlock, и текст исчез бы бесследно.
        warn("gost_htmldiv: после <div ...> нужна пустая строка, иначе "
             .. "содержимое блока не попадёт в DOCX")
      end
      -- Прочий сырой HTML в DOCX не переносится: pandoc его отбрасывает.
    else
      sink(block)
    end
  end

  -- Незакрытые блоки: отдаём содержимое, а не теряем документ.
  while #stack > 0 do
    warn("gost_htmldiv: не найден закрывающий </div> — блок закрыт автоматически")
    close_top()
  end

  return pandoc.Pandoc(out, doc.meta)
end
