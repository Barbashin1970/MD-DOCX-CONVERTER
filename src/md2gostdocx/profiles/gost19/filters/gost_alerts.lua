-- GitHub-alerts (> [!NOTE]) -> custom-style Word
local MAP = { note="Note", tip="Tip", important="Important",
              warning="Warning", caution="Caution" }
local RU  = { note="Примечание", tip="Совет", important="Важно",
              warning="Внимание", caution="Осторожно" }
function Div(el)
  for _, c in ipairs(el.classes) do
    if MAP[c] then
      -- заменить английский заголовок алерта русским
      local blocks = pandoc.List({})
      for _, b in ipairs(el.content) do
        if b.t == "Div" and b.classes:includes("title") then
          blocks:insert(pandoc.Para({ pandoc.Strong({ pandoc.Str(RU[c]) }) }))
        else
          blocks:insert(b)
        end
      end
      return pandoc.Div(blocks,
        pandoc.Attr("", {}, { ["custom-style"] = MAP[c] }))
    end
  end
end
