Attribute VB_Name = "工作表4"
Attribute VB_Base = "0{00020820-0000-0000-C000-000000000046}"
Attribute VB_GlobalNameSpace = False
Attribute VB_Creatable = False
Attribute VB_PredeclaredId = True
Attribute VB_Exposed = True
Attribute VB_TemplateDerived = False
Attribute VB_Customizable = True
Attribute VB_Control = "CheckBox1, 57, 0, MSForms, CheckBox"
Attribute VB_Control = "CommandButton1, 5, 1, MSForms, CommandButton"
Private Sub CheckBox1_Click()

    Dim PE_公開Cht As ChartObject
    Dim PE_計算Cht As ChartObject
    Set PE_公開Cht = Me.ChartObjects("歷年本益比(公開資訊)")
    PE_公開Cht.Visible = CheckBox1.Value
    Set PE_計算Cht = Me.ChartObjects("歷年本益比(自行計算)")
    PE_計算Cht.Visible = CheckBox1.Value

End Sub

Private Sub CommandButton1_Click()

'    theDate = Application.IfError(Application.VLookup(Sheets("評價簡表").Range("B1"), Sheets("股票代號").Range("A:F"), 3, False), "")
    theDate = Sheets("BASIC").Range("C19")      '110/7/6 更改為判斷初次上市(櫃)日期
    If theDate <> "" Then       ''110/4/5
        theYear = Year(theDate)
    Else
        MsgBox ("找不到[評價簡表]->[B1]所輸入的股票代號，無法更新相關數據，請到[評價簡表]->[B1]輸入正確代號，重新查詢 !!!")
        Exit Sub
    End If
    If theYear = Year(Now) - 1911 Then    '110/4/5；110/8/17 因BASIC工作表之初次上市(櫃)日期年度為民國年，故修正
        MsgBox ("今年上市櫃個股，暫無法預估EPS !!!")
        Exit Sub
    End If
    If Sheets("營收").Range("P6") <> 0 Then     '110/4/5
        MsgBox ("財報數據不足四季，無法預估EPS !!!")
        Exit Sub
    End If
    If Sheets("EPS預估與估價").Range("D1") <> "" Then     '110/5/12
        MsgBox ("金融保險業不適用，暫無法預估EPS !!!")
        Exit Sub
    End If
    tt = Timer      '109/03/26 計算查詢秒數
    Range("AF1") = 0
    
    flag = 0        '109/1/4 判斷是否需下載每日股價
    If Range("A1") <> Sheets("營收").Range("A1") Then
        Range("AF4:AF9") = 0    '109/03/26
        Range("AG4:AG9") = ""    '109/03/26，110/5/12
'        110/5/12[外資投信]之三大法人持股及買賣超數據，修改為手動抓取
'        Range("AG4:AG10") = ""    '110/1/9
        Range("A1") = Sheets("營收").Range("A1")
        flag = 1
'        Range("O4:O15").ClearContents
        Range("O4:O13").ClearContents   '109/2/25
    End If
    
'    Range("A4:I15").ClearContents
'    Range("A4:I14").ClearContents       '109/2/16 在第15列判斷12月公布月營收時, 顯示預估Q3財報年度之EPS
    Range("A4:I13").ClearContents       '109/2/18 在第14列顯示最新月營收公布時, 最新預估之EPS
    Range("A34:I40").ClearContents
    Range("K34:S40").ClearContents
    Range("L1") = ""                    '110/1/6 清空"手動預估EPS(1)"[L1]欄位
    Range("K15:L15") = ""          '110/4/13 清空"手動本益比高/低點"欄位
    Range("AD2") = ""                    '110/2/12 清空"手動EPS成長率"[AD2]欄位
    Sheets("殖利率估價").Range("K1") = ""                    '110/1/9 清空"手動預估股利發放率"[K1]欄位
    Sheets("殖利率估價").Range("M1") = ""                    '110/1/9 清空"手動預估EPS"[M1]欄位
    Sheets("殖利率估價").Range("O1") = ""                    '110/2/12 清空"手動預估BPS"[M1]欄位
    Sheets("河流圖").Range("N2:N3").ClearContents
    Sheets("河流圖").Range("AC2:AC3").ClearContents          '110/2/12 清空"自估BPS"[AC2~AC3]欄位
    
'    Application.EnableEvents = False
    Application.Calculation = xlCalculationManual
    Application.ScreenUpdating = False
    
    '計算公布之營收日期以預估EPS
    Pos = 14    '營收當月row=8，前6個月row=14
    StartCount = 34
    EndCount = StartCount + 6
    For i = StartCount To EndCount
        Range("B" & i) = Sheets("營收").Range("A" & Pos)
        Mon = Right(Range("B" & i), 2)
        If Mon <> "12" Then
            Range("A" & i) = Left(Range("B" & i), 4) & WorksheetFunction.VLookup(Mon, Sheets("營收").Range("I21:L37"), 2, False)
        Else
            Range("A" & i) = Left(Range("B" & i), 3) + 1 & "/" & WorksheetFunction.VLookup(Mon, Sheets("營收").Range("I21:L37"), 2, False)
        End If
        If Sheets("EPS預估與估價").Range("D2") = "1&6月營收孰低" Then    '109/1/4 判斷預估營收是採用1&6月營收孰低 或 近12月累積營收
'            Range("C" & i) = Sheets("營收").Range("I8") / 1000      '去年全年 營收
            Range("C" & i) = Sheets("營收").Range("I" & Pos) / 1000      '109/2/15 去年全年 營收
            Range("D" & i) = Sheets("營收").Range("K" & Pos)        '預估營收成長率
            Range("E" & i) = Range("C" & i) * (1 + Range("D" & i))      '預估營收
        ElseIf Sheets("EPS預估與估價").Range("D2") = "3&6月營收孰低" Then    '109/2/9 新增判斷預估營收採用3&6月營收孰低
'            Range("C" & i) = Sheets("營收").Range("I8") / 1000      '去年全年 營收
            Range("C" & i) = Sheets("營收").Range("I" & Pos) / 1000      '109/2/15 去年全年 營收
            Range("D" & i) = Sheets("營收").Range("M" & Pos)        '預估營收成長率
            Range("E" & i) = Range("C" & i) * (1 + Range("D" & i))      '預估營收
        Else
'            Range("C" & i) = Sheets("營收").Range("W" & Pos + 12) / 1000    '去年近12月累積營收
'            Range("D" & i) = Sheets("營收").Range("X" & Pos)               '預估營收成長率
'            Range("C" & i) = Sheets("營收").Range("Y" & pos + 12) / 1000    '109/2/9 新增去年近12月累積營收，位置位移
            Range("C" & i) = Sheets("營收").Range("I" & Pos) / 1000    '109/2/15 修改為去年全年 營收
            Range("D" & i) = Sheets("營收").Range("Z" & Pos)
            Range("E" & i) = Range("C" & i) * (1 + Range("D" & i))      '預估營收
        End If
        年度 = Left(Range("B" & i), 3) + 1911 + WorksheetFunction.VLookup(Mon, Sheets("營收").Range("I21:L37"), 4, False)
        季度 = WorksheetFunction.VLookup(Mon, Sheets("營收").Range("I21:L37"), 3, False)
        財報季度 = 年度 & "." & 季度
'        財報季度位置0 = 13 + WorksheetFunction.Match(財報季度, Sheets("營收").Range("N7:U7"), 0)
        財報季度位置0 = 15 + WorksheetFunction.Match(財報季度, Sheets("營收").Range("P7:W7"), 0)    '109/2/9 新增用3&6月營收孰低，位置位移
'        Range("F" & i) = (Sheets("營收").Cells(14, 財報季度位置0) + Sheets("營收").Cells(14, 財報季度位置0 + 1) + Sheets("營收").Cells(14, 財報季度位置0 + 2) + Sheets("營收").Cells(14, 財報季度位置0 + 3)) / 4    '本期稅後淨利率(4季平均)
        '110/9/20 本期稅後淨利率可選擇採用4季平均、4季最低淨利率或本季
        If Range("F16") = "4季最低" Then
            Range("F" & i) = Application.Min(Sheets("營收").Cells(14, 財報季度位置0), Sheets("營收").Cells(14, 財報季度位置0 + 1), Sheets("營收").Cells(14, 財報季度位置0 + 2), Sheets("營收").Cells(14, 財報季度位置0 + 3))
        ElseIf Range("F16") = "本季" Then
            Range("F" & i) = Sheets("營收").Cells(14, 財報季度位置0)
        Else
            Range("F" & i) = Application.Average(Sheets("營收").Cells(14, 財報季度位置0), Sheets("營收").Cells(14, 財報季度位置0 + 1), Sheets("營收").Cells(14, 財報季度位置0 + 2), Sheets("營收").Cells(14, 財報季度位置0 + 3))        '110/4/1
        End If
        Range("G" & i) = Range("E" & i) * Range("F" & i)      '預估淨利
        '110/9/20 可自訂加權平均股數
        If Range("H16") = "" Then
            Range("H" & i) = Sheets("營收").Cells(15, 財報季度位置0)    '加權平均股數
        Else
            Range("H" & i) = Range("H16")       '自訂加權平均股數
        End If
        Range("I" & i) = Range("G" & i) / Range("H" & i)    '預估EPS
        Pos = Pos - 1
    Next i
       
    '計算公布之季度財報以調整預估EPS
    Pos = 14
    i = 34
    Do
        Mon = Right(Sheets("營收").Range("A" & Pos), 2)
        tmpRow = 20 + WorksheetFunction.Match(Mon, Sheets("營收").Range("I21:I37"), 0)
        If Sheets("營收").Range("I" & tmpRow) = Sheets("營收").Range("I" & tmpRow + 1) Then     '判斷同月份營收是否有跨季度財報，如08/10發布7月營收時，財報是1Q，但到08/15公布2Q財報時，營收還是7月
            Range("L" & i) = Sheets("營收").Range("A" & Pos)
            Range("K" & i) = Left(Range("L" & i), 4) & Sheets("營收").Range("J" & tmpRow + 1)
            If Sheets("EPS預估與估價").Range("D2") = "1&6月營收孰低" Then    '109/1/4 判斷預估營收是採用1&6月營收孰低 或 近12月累積營收
'                Range("M" & i) = Sheets("營收").Range("I8") / 1000      '去年全年 營收
                Range("M" & i) = Sheets("營收").Range("I" & Pos) / 1000      '109/2/15 去年全年 營收
                Range("N" & i) = Sheets("營收").Range("K" & Pos)        '預估營收成長率
                Range("O" & i) = Range("M" & i) * (1 + Range("N" & i))      '預估營收
            ElseIf Sheets("EPS預估與估價").Range("D2") = "3&6月營收孰低" Then    '109/2/9 新增判斷預估營收採用1&6月營收孰低
'                Range("M" & i) = Sheets("營收").Range("I8") / 1000      '去年全年 營收
                Range("M" & i) = Sheets("營收").Range("I" & Pos) / 1000      '109/2/15 去年全年 營收
                Range("N" & i) = Sheets("營收").Range("M" & Pos)        '預估營收成長率
                Range("O" & i) = Range("M" & i) * (1 + Range("N" & i))      '預估營收
            Else
'                Range("M" & i) = Sheets("營收").Range("W" & Pos + 12) / 1000
'                Range("N" & i) = Sheets("營收").Range("X" & Pos)
'                Range("M" & i) = Sheets("營收").Range("Y" & pos + 12) / 1000    '109/2/9 新增3&6月營收孰低，位置位移
                Range("M" & i) = Sheets("營收").Range("I" & Pos) / 1000    '109/2/15 修改為去年全年 營收
                Range("N" & i) = Sheets("營收").Range("Z" & Pos)
                Range("O" & i) = Range("M" & i) * (1 + Range("N" & i))      '預估營收
            End If
            年度 = Left(Range("L" & i), 3) + 1911 + Sheets("營收").Range("L" & tmpRow + 1)
            季度 = Sheets("營收").Range("K" & tmpRow + 1)
            財報季度 = 年度 & "." & 季度
'            財報季度位置0 = 13 + WorksheetFunction.Match(財報季度, Sheets("營收").Range("N7:U7"), 0)
            財報季度位置0 = 15 + WorksheetFunction.Match(財報季度, Sheets("營收").Range("P7:W7"), 0)    '109/2/9 新增用3&6月營收孰低，位置位移
'            Range("P" & i) = (Sheets("營收").Cells(14, 財報季度位置0) + Sheets("營收").Cells(14, 財報季度位置0 + 1) + Sheets("營收").Cells(14, 財報季度位置0 + 2) + Sheets("營收").Cells(14, 財報季度位置0 + 3)) / 4
            '110/9/20 本期稅後淨利率可選擇採用4季平均、4季最低淨利率或本季
            If Range("F16") = "4季最低" Then
                Range("P" & i) = Application.Min(Sheets("營收").Cells(14, 財報季度位置0), Sheets("營收").Cells(14, 財報季度位置0 + 1), Sheets("營收").Cells(14, 財報季度位置0 + 2), Sheets("營收").Cells(14, 財報季度位置0 + 3))
            ElseIf Range("F16") = "本季" Then
                Range("P" & i) = Sheets("營收").Cells(14, 財報季度位置0)
            Else
                Range("P" & i) = Application.Average(Sheets("營收").Cells(14, 財報季度位置0), Sheets("營收").Cells(14, 財報季度位置0 + 1), Sheets("營收").Cells(14, 財報季度位置0 + 2), Sheets("營收").Cells(14, 財報季度位置0 + 3))        '110/4/1
            End If
            Range("Q" & i) = Range("O" & i) * Range("P" & i)      '預估淨利
             '110/9/20 可自訂加權平均股數
            If Range("H16") = "" Then
                Range("R" & i) = Sheets("營收").Cells(15, 財報季度位置0)    '加權平均股數
            Else
                Range("R" & i) = Range("H16")       '自訂加權平均股數
            End If
            Range("S" & i) = Range("Q" & i) / Range("R" & i)    '預估EPS
            i = i + 1
        End If
        Pos = Pos - 1
    Loop Until Pos = 8
    
    '109/3/7 將最後一筆營收月份獨立判斷，額外判斷同月份跨季度財報是否與最新季報季度一樣，避免當誤判可跨季度，但實際該季度財報尚未公布，而發生錯誤訊息
    Mon = Right(Sheets("營收").Range("A" & Pos), 2)
    tmpRow = 20 + WorksheetFunction.Match(Mon, Sheets("營收").Range("I21:I37"), 0)
    If Sheets("營收").Range("K" & tmpRow + 1) = Right(Sheets("營收").Range("P7"), 2) Then  '109/3/7 判斷同月份跨季度財報是否與最新季報季度一樣
        If Sheets("營收").Range("I" & tmpRow) = Sheets("營收").Range("I" & tmpRow + 1) Then     '判斷同月份營收是否有跨季度財報，如08/10發布7月營收時，財報是1Q，但到08/15公布2Q財報時，營收還是7月
            Range("L" & i) = Sheets("營收").Range("A" & Pos)
            Range("K" & i) = Left(Range("L" & i), 4) & Sheets("營收").Range("J" & tmpRow + 1)
            If Sheets("EPS預估與估價").Range("D2") = "1&6月營收孰低" Then    '109/1/4 判斷預估營收是採用1&6月營收孰低 或 近12月累積營收
'                Range("M" & i) = Sheets("營收").Range("I8") / 1000      '去年全年 營收
                Range("M" & i) = Sheets("營收").Range("I" & Pos) / 1000      '109/2/15 去年全年 營收
                Range("N" & i) = Sheets("營收").Range("K" & Pos)        '預估營收成長率
                Range("O" & i) = Range("M" & i) * (1 + Range("N" & i))      '預估營收
            ElseIf Sheets("EPS預估與估價").Range("D2") = "3&6月營收孰低" Then    '109/2/9 新增判斷預估營收採用1&6月營收孰低
'                Range("M" & i) = Sheets("營收").Range("I8") / 1000      '去年全年 營收
                Range("M" & i) = Sheets("營收").Range("I" & Pos) / 1000      '109/2/15 去年全年 營收
                Range("N" & i) = Sheets("營收").Range("M" & Pos)        '預估營收成長率
                Range("O" & i) = Range("M" & i) * (1 + Range("N" & i))      '預估營收
            Else
'                Range("M" & i) = Sheets("營收").Range("W" & Pos + 12) / 1000
'                Range("N" & i) = Sheets("營收").Range("X" & Pos)
'                Range("M" & i) = Sheets("營收").Range("Y" & pos + 12) / 1000    '109/2/9 新增3&6月營收孰低，位置位移
                Range("M" & i) = Sheets("營收").Range("I" & Pos) / 1000    '109/2/15 修改為去年全年 營收
                Range("N" & i) = Sheets("營收").Range("Z" & Pos)
                Range("O" & i) = Range("M" & i) * (1 + Range("N" & i))      '預估營收
            End If
            年度 = Left(Range("L" & i), 3) + 1911 + Sheets("營收").Range("L" & tmpRow + 1)
            季度 = Sheets("營收").Range("K" & tmpRow + 1)
            財報季度 = 年度 & "." & 季度
'            財報季度位置0 = 13 + WorksheetFunction.Match(財報季度, Sheets("營收").Range("N7:U7"), 0)
            財報季度位置0 = 15 + WorksheetFunction.Match(財報季度, Sheets("營收").Range("P7:W7"), 0)    '109/2/9 新增用3&6月營收孰低，位置位移
'            Range("P" & i) = (Sheets("營收").Cells(14, 財報季度位置0) + Sheets("營收").Cells(14, 財報季度位置0 + 1) + Sheets("營收").Cells(14, 財報季度位置0 + 2) + Sheets("營收").Cells(14, 財報季度位置0 + 3)) / 4
            '110/9/20 本期稅後淨利率可選擇採用4季平均、4季最低淨利率或本季
            If Range("F16") = "4季最低" Then
                Range("P" & i) = Application.Min(Sheets("營收").Cells(14, 財報季度位置0), Sheets("營收").Cells(14, 財報季度位置0 + 1), Sheets("營收").Cells(14, 財報季度位置0 + 2), Sheets("營收").Cells(14, 財報季度位置0 + 3))
            ElseIf Range("F16") = "本季" Then
                Range("P" & i) = Sheets("營收").Cells(14, 財報季度位置0)
            Else
                Range("P" & i) = Application.Average(Sheets("營收").Cells(14, 財報季度位置0), Sheets("營收").Cells(14, 財報季度位置0 + 1), Sheets("營收").Cells(14, 財報季度位置0 + 2), Sheets("營收").Cells(14, 財報季度位置0 + 3))        '110/4/1
            End If
            Range("Q" & i) = Range("O" & i) * Range("P" & i)      '預估淨利
             '110/9/20 可自訂加權平均股數
            If Range("H16") = "" Then
                Range("R" & i) = Sheets("營收").Cells(15, 財報季度位置0)    '加權平均股數
            Else
                Range("R" & i) = Range("H16")       '自訂加權平均股數
            End If
            Range("S" & i) = Range("Q" & i) / Range("R" & i)    '預估EPS
            i = i + 1
        End If
    End If
    
    Range("K" & i) = Year(Now) - 1911 + 1 & "/12/31"  '107/06/10 避免A33預估日期(最後一筆)>K33預估日期(最後一筆)，造成If Range("A" & a) < Range("K" & k) 誤判
    EndCount2 = i - 1
        
    '合併公布之營收及季度財報以預估EPS
'    Range("A34").Select
'    Range("A34:I34").Copy
'    Application.Wait (Now + TimeValue("00:00:01"))     '109/04/02 有時會出現錯誤，故延遲1秒
'    Range("A4").PasteSpecial xlPasteValues
    For i = 1 To 9      '109/04/03 因應有時會出現錯誤，故改變寫法
        Cells(4, i) = Cells(34, i)
    Next i

    lastrow_A = Range("A33").End(xlDown).Row
    lastrow_K = Range("K33").End(xlDown).Row - 1   '107/06/10
    a0 = 5
    a = 35
    k = 34
    
    Do
        If Range("A" & a) < Range("K" & k) And Range("A" & a) <> "" Then
            'Range("A" & a0) = Range("A" & a)
            Range("A" & a & ":I" & a).Copy
            Range("A" & a0).PasteSpecial xlPasteValues
            a0 = a0 + 1
            a = a + 1
        Else
            'Range("A" & a0) = Range("K" & k)
            Range("K" & k & ":S" & k).Copy
            Range("A" & a0).PasteSpecial xlPasteValues
            k = k + 1
            a0 = a0 + 1
        End If
    Loop Until a > lastrow_A And k > lastrow_K
    Range("A1").Select
    Application.CutCopyMode = False
    Application.ScreenUpdating = True

'    Application.Calculation = xlCalculationAutomatic       '調整至最後一列，增加效能(減少總查詢時間)
    
    '------------下載每日股價及計算報酬風險
'    Range("O4:O15").ClearContents
'    Application.ScreenUpdating = False   '畫面不會跳動
    
    If flag = 1 Then        '109/1/4 判斷是否需下載每日股價
        股號 = Mid(Range("A1"), Len(Range("A1")) - 5, 4)
        
        '109/3/1 抓取計算歷年最高最低本益比所需之年度交易資訊 ---Begin
        Application.StatusBar = "開始抓取年度交易資訊，請稍待..."
'        Application.ScreenUpdating = True
        t0 = Timer
'        WebQuery_TAIEX_YTV 股號, "年度交易資訊"
        Query_TAIEX_YTV_NEW 股號, "年度交易資訊"    '109/9/13 改寫"年度交易資訊"程式，改善抓取速度
        Range("AG4") = WorksheetFunction.Round(Timer - t0, 2)
        '109/03/26
        If Sheets("年度交易資訊").Range("A2") <> "" Then
            Range("AF4") = 1
        End If
        Application.StatusBar = "開始抓取年度交易資訊(上櫃)，請稍待..."
        t0 = Timer
        '109/5/2 例外處理有些人電腦環境無法用Excel抓取上櫃個股年度交易資訊的問題
        '若按[預估EPS]，卡在"開始抓取年度交易資訊(上櫃)，請稍待..."，請在[設定]->[G3]選擇"備用"，再重按[預估EPS]
        If Sheets("設定").Range("G3") = "正常" Then
            WebQuery_TAIEX_YTV2 股號, "年度交易資訊(上櫃)"
            Sheets("年度交易資訊(上櫃)").Columns(5).EntireColumn.Delete      '10/12/28 修正因櫃買中心網站改版，抓取上櫃股票年度交易資訊時，多E欄"加權平均價 (B/A)"，導致最高/低價位置位移，而錯誤計算本益比等問題
            If Sheets("年度交易資訊(上櫃)").Range("A1") <> "" Then      ' 113/11/05 因應櫃買中心網站更版更改網址
                RowEnd = Sheets("年度交易資訊(上櫃)").Range("A1").End(xlDown).Row
                Sheets("年度交易資訊(上櫃)").Range("A2:" & "I" & RowEnd).Cut Destination:=Sheets("年度交易資訊(上櫃)").Range("A4")
            End If
        Else    ' 113/11/05 因應櫃買中心網站更版更改網址，不再使用
            WebQuery_TAIEX_YTV2_bck 股號, "年度交易資訊(上櫃)"
            Sheets("年度交易資訊(上櫃)").Columns(5).EntireColumn.Delete      '10/12/28
        End If
        Range("AG5") = WorksheetFunction.Round(Timer - t0, 2)
        '109/03/26
        If Sheets("年度交易資訊(上櫃)").Range("A1") <> "" Then
            Range("AF5") = 1
        End If
        Application.ScreenUpdating = False
        Application.StatusBar = "上市櫃年度交易資訊合併，請稍待..."
        MergeYTV_New "年度交易資訊(上市櫃合併)", "年度交易資訊", "年度交易資訊(上櫃)"       '111/1/5 改用陣列，加快執行速度
        '109/3/1 抓取計算歷年最高最低本益比所需之年度交易資訊 ---End
        
        '110/1/10 因近日從cnyes(Anue鉅亨)抓取日股價時，不時有抓不到現象，改可選擇從其他證券網站抓
        Application.ScreenUpdating = True
        If Sheets("設定").Range("G5") = "鉅亨網" Then
            sYear = Year(Now) - 1
    '        sMon = Mid(Range("A4"), 4, 3)
            sMon = "/01"
            查詢起始日 = WorksheetFunction.Text(sYear & sMon & "/01", "yyyy/mm/dd")
            Application.StatusBar = "開始抓取股價(日)，請稍待..."
            t0 = Timer
            WebQuery_HIS_STOCK_PRICE 股號, 查詢起始日
            Range("AG6") = WorksheetFunction.Round(Timer - t0, 2)
            '109/03/26
            If Sheets("股價(日)").Range("A2") <> "" Then
                Range("AF6") = 1
            End If
        Else
            '110/1/10 改其他證券網站抓
            Dim arrData(1 To 520, 1 To 8)
            SName = "股價(日)2"
            股號 = Mid(Sheets("EPS預估與估價").Range("A1"), Len(Sheets("EPS預估與估價").Range("A1")) - 5, 4)
            Application.StatusBar = "開始抓取股價(日)2，請稍待..."
            t0 = Timer
            MoneyDJ_TW_PRICE_New SName, 股號, "D"       '111/1/8 改用陣列，加快執行速度
            Range("AG6") = WorksheetFunction.Round(Timer - t0, 2)
            If Sheets("股價(日)2").Range("C1") <> "" Then
                Range("AF6") = 1
            End If
            
            Application.ScreenUpdating = False
            With Sheets("股價(日)2")
                RowEnd = .Range("S1").End(xlDown).Row
                 If .Range("S" & RowEnd) > .Range("S2") Then       '110/3/29 例外判斷個股股歷史價格只有當年度的情形
                    LastYear = .Range("S" & RowEnd) - 1
                Else
                    LastYear = .Range("S" & RowEnd)
                End If
                RowBgn = WorksheetFunction.Match(LastYear, .Range("S:S"), 0)
                wr = 1
                For i = RowEnd To RowBgn Step -1
                    wc = 21
                    arrData(wr, 1) = WorksheetFunction.Text(.Cells(i, 20), "yyyy/mm/dd")      '日期
                    For j = 2 To 5
                        arrData(wr, j) = .Cells(i, wc)      '開盤    最高    最低    收盤
                        wc = wc + 1
                    Next
                    If i <> 2 Then
                        arrData(wr, 6) = .Cells(i, 24) - .Cells(i - 1, 24)      '漲跌
                        arrData(wr, 7) = (.Cells(i, 24) - .Cells(i - 1, 24)) / .Cells(i - 1, 24)    '漲%
                    Else
                        arrData(wr, 6) = ""      '漲跌
                        arrData(wr, 7) = ""    '漲%
                    End If
                    arrData(wr, 8) = .Cells(i, 25)          '成交量
                    wr = wr + 1
                Next
                Sheets("股價(日)").Range("A2:J520").ClearContents
                Sheets("股價(日)").Range("A2:A520").NumberFormatLocal = "@"    '轉為文字格式，避免鉅亨網抓過後又變為日期格式
                Sheets("股價(日)").Range("A2").Resize(520, 8) = arrData        'copy到[股價(日)]工作表
            End With
        End If

        Application.Calculation = xlCalculationAutomatic        '109/03/26調整至此，增加效能(減少總查詢時間)

        If Sheets("股價(日)").Range("A2") <> 0 Then     '109/03/29 新增判斷"股價(日)"無法下載
            For i = 4 To 13     '109/2/25
                If Range("A" & i) <> "" Then
                    '110/3/18
'                    Range("O" & i) = WorksheetFunction.Index(Sheets("股價(日)").Range("L:M"), WorksheetFunction.Match(Range("A" & i), Sheets("股價(日)").Range("L:L"), -1), 2)
                    StockPrice = WorksheetFunction.Index(Sheets("股價(日)").Range("L:M"), WorksheetFunction.Match(Range("A" & i), Sheets("股價(日)").Range("L:L"), -1), 2)
                    If StockPrice <> "收盤" Then    '108/10/10 若預估日期股市休市，則市價取休市前一天收盤價
                        Range("O" & i) = StockPrice
                    Else
                        Range("O" & i) = Sheets("股價(日)").Range("M2")
                    End If
                End If
            Next i
        End If
'        Application.ScreenUpdating = False
        
        '109/3/1 抓取計算歷年最高最低本益比所需之年度交易資訊 ---Begin
         '合併當年度交易資訊
        市場別 = Trim(WorksheetFunction.VLookup(CInt(股號), Sheets("股票代號").Range("A:D"), 4, False))     '110/12/10 去除頭尾空白
        If 市場別 = "上市" Then
            TWSE_PRICE_DAY2YEAR_cnYES ("股價(日)")
            Sheets("年度交易資訊(上市櫃合併)").Range("A13") = "當年度"
            If Sheets("股價(日)").Range("K1") <> 0 Then     '109/03/29 新增判斷"股價(日)"無法下載
                lastrow = Sheets("年度交易資訊").Range("A1").End(xlDown).Row
                Sheets("年度交易資訊").Range("A" & lastrow & ":I" & lastrow).Copy     '當年度成交資訊
                Sheets("年度交易資訊(上市櫃合併)").Range("A14").PasteSpecial xlPasteValues
            End If
        Else
            Sheets("年度交易資訊(上市櫃合併)").Range("A13") = "當年度"
            Sheets("年度交易資訊(上櫃)").Range("A5:I5").Copy     '當年度成交資訊
            Sheets("年度交易資訊(上市櫃合併)").Range("A14").PasteSpecial xlPasteValues
        End If
        Sheets("年度交易資訊(上市櫃合併)").Activate
        Sheets("年度交易資訊(上市櫃合併)").Range("A1").Select
        Application.CutCopyMode = False
        Sheets("EPS預估與估價").Activate
        
     
        '109/3/1 抓取計算歷年最高最低本益比所需之年度交易資訊 ---End
        
'        Application.ScreenUpdating = False
        '------------109/1/9 抓年財務比率(每股稅後盈餘及每股淨值)
        '------------109/2/13 因只有少數財報數據缺漏情形，增加使用者可設定是否要抓Goodinfo年財務比率資料，除加速資料下載，也避免Excel 2019發生錯誤現象(暫時作法)
        If (Sheets("設定").Range("G1") = "Y") Then
            SName_G = "Goodinfo年財務比率"
            Application.StatusBar = "開始抓取Goodinfo年財務比率資料，請稍待..."
            Application.ScreenUpdating = True
            t0 = Timer
            Get_data_from_GoodInfo_財務比率 股號, SName_G
            Range("AG7") = WorksheetFunction.Round(Timer - t0, 2)
            '109/03/26
            If Sheets("設定").Range("G1") <> "N" And Sheets("Goodinfo年財務比率").Range("A1") <> "" Then
                Range("AF7") = 1
            End If
            Application.ScreenUpdating = False
        End If
        SName_M = "MoneyDJ年財務比率"
        Application.StatusBar = "開始抓取MoneyDJ年財務比率資料，請稍待..."
        Application.ScreenUpdating = True
        t0 = Timer
        Get_data_from_MoneyDJ_年財務比率 股號, SName_M
        Range("AG8") = WorksheetFunction.Round(Timer - t0, 2)
        '109/03/26
'        If Sheets("評價簡表").Range("B1") = CInt(Right(Left(Sheets("MoneyDJ年財務比率").Range("B4"), Len(Sheets("MoneyDJ年財務比率").Range("B4")) - 6), 4)) Then
        If Sheets("評價簡表").Range("B1") = CInt(Right(Left(Sheets("MoneyDJ年財務比率").Range("A3"), Len(Sheets("MoneyDJ年財務比率").Range("A3")) - 6), 4)) Then            '110/12/25
            Range("AF8") = 1
        End If
        Application.ScreenUpdating = False
        
        '------------109/1/9 計算每股稅後盈餘及每股淨值，比較Goodinfo年財務比率及MoneyDJ年財務比率，取其大
        SName = "股價(週)"
        If (Sheets("設定").Range("G1") = "Y") Then
'            If (Sheets(SName_G).Range("B1") = Sheets(SName_M).Range("C7")) Then     '109/3/9 增加判斷[Goodinfo年財務比率]與[MoneyDJ年財務比率]之最新財報需同年度，才比較兩者數據，以避免程式誤抓比財報更早年度的股價，而導致錯誤
            If (Sheets(SName_G).Range("B1") = Sheets(SName_M).Range("B6")) Then     '110/12/25
                計算EPS_BPS SName, SName_M, SName_G
            Else
                計算EPS_BPS2 SName, SName_M
            End If
        Else
            計算EPS_BPS2 SName, SName_M
        End If
        
        '------------109/1/9 下載每週股價
        SName = "股價(週)"
        Application.StatusBar = "開始抓取每週股價，請稍待..."
        Application.ScreenUpdating = True
        t0 = Timer
        MoneyDJ_TW_PRICE_New SName, 股號, "W"       '111/1/8 改用陣列，加快執行速度
        Range("AG9") = WorksheetFunction.Round(Timer - t0, 2)
        '109/03/26
        If Sheets("股價(週)").Range("S2") <> "" Then
            Range("AF9") = 1
        End If
        Application.StatusBar = False
        
        '------------110/1/9 下載三大法人買賣超
        '110/5/12[外資投信]之三大法人持股及買賣超數據，修改為手動抓取

'        SName = "三大法人"
'        Application.StatusBar = "開始抓取三大法人買賣超，請稍待..."
'        Application.ScreenUpdating = True
'        t0 = Timer
'        StartDate = WorksheetFunction.Text(Sheets("股價(日)").Range("A21"), "yyyy-m-d")
'        EndDate = WorksheetFunction.Text(Sheets("股價(日)").Range("A2"), "yyyy-m-d")
'        Get_法人持股 股號, SName, StartDate, EndDate
'        Range("AG10") = WorksheetFunction.Round(Timer - t0, 2)
'        Application.StatusBar = False
'
'        YearBgn = Sheets("MoneyDJ年財務比率").Range("J7")
        YearBgn = Sheets("MoneyDJ年財務比率").Range("I6")           '110/12/25
        SName = "股價(週)"      '110/1/9
        計算河流圖股價 SName, YearBgn
    Else
        Application.Calculation = xlCalculationAutomatic
    End If
    
    
    If Sheets("股價(日)").Range("A2") <> "" Then    '109/03/29 新增判斷是否已下載
        If Range("A" & EndCount) > Range("K" & EndCount2) Then
            If Range("A" & EndCount) > Sheets("股價(日)").Range("L2") Then      '109/1/10 判斷若最後一筆每月營收預定公布日 > 最新股價日期，則改為最新股價日期
                Range("A" & a0 - 1) = Sheets("股價(日)").Range("L2")
            End If
        Else
            If Range("K" & EndCount2) > Sheets("股價(日)").Range("L2") Then      '109/3/12 判斷若最後一筆財報預定公布日 > 最新股價日期，則改為最新股價日期
                Range("A" & a0 - 1) = Sheets("股價(日)").Range("L2")
            End If
        End If
    End If

    Range("H1") = Sheets("FRQ").Range("L5")     '109/3/8 當按[預估EP]時，並不會自動更新選單年度數據，故強迫更新
'    If Range("B15") <> "" Then                  '110/2/12 強制回復該欄位之公式，以防手動更新此欄位之預估EPS值，110/4/13 移除if
        Range("I15").Formula = "=IFERROR(G15/H15, """")"
'    End If
    
'    Application.ScreenUpdating = True
'    Application.EnableEvents = True
    Range("AF1") = WorksheetFunction.Round(Timer - tt, 2)


End Sub
