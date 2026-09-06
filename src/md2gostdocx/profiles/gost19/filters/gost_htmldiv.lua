-- <div class="requirement"> ... </div> из GFM -> Div с custom-style Word.
-- На GitHub такой блок рендерится обычным текстом (тег скрыт), в DOCX получает стиль.
local MAP = { requirement = "Requirement", note = "Note",
              warning = "Warning", term = "Term",
              tip = "Tip", important = "Important", caution = "Caution",
              ["requirements-table"] = "RequirementsTable",
              ["terms-table"] = "TermsTable" }

function Pandoc(doc)
  local out, stack = pandoc.List({}), {}
  local function sink(b)
    if #stack > 0 then stack[#stack].blocks:insert(b) else out:insert(b) end
  end
  for _, b in ipairs(doc.blocks) do
    if b.t == "RawBlock" and b.format == "html" then
      local cls = b.text:match('^%s*<div%s+class="([%w_-]+)"%s*>')
      if cls then
        stack[#stack+1] = { cls = cls, blocks = pandoc.List({}) }
        goto next
      end
      if b.text:match("^%s*</div>") and #stack > 0 then
        local top = table.remove(stack)
        local style = MAP[top.cls] or top.cls
        sink(pandoc.Div(top.blocks,
             pandoc.Attr("", {}, { ["custom-style"] = style })))
        goto next
      end
      goto next            -- прочий сырой HTML просто отбрасываем
    end
    sink(b)
    ::next::
  end
  return pandoc.Pandoc(out, doc.meta)
end
