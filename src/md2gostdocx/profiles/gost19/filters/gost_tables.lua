-- Ширина таблиц на всю полосу набора.
--
-- Читатель gfm не отдаёт ширины колонок, и pandoc пишет tblW auto с сеткой в
-- 7920 twips независимо от размера страницы — это и есть «таблицы сжаты» из
-- §4.5.2 ТЗ. Как только у таблицы появляются colspecs с суммой 1.0, pandoc
-- сам ставит tblW pct=5000 и tblLayout fixed.
--
-- Пропорции сохраняются, если они заданы; иначе колонки делятся поровну.

function Table (tbl)
  local specs = tbl.colspecs
  local count = #specs
  if count == 0 then return nil end

  local total = 0
  for i = 1, count do
    total = total + (specs[i][2] or 0)
  end

  for i = 1, count do
    local width = specs[i][2]
    if total > 0 and width then
      specs[i] = { specs[i][1], width / total }
    else
      specs[i] = { specs[i][1], 1.0 / count }
    end
  end

  tbl.colspecs = specs
  return tbl
end
