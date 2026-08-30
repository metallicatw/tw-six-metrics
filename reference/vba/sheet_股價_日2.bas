Attribute VB_Name = "工作表36"
Attribute VB_Base = "0{00020820-0000-0000-C000-000000000046}"
Attribute VB_GlobalNameSpace = False
Attribute VB_Creatable = False
Attribute VB_PredeclaredId = True
Attribute VB_Exposed = True
Attribute VB_TemplateDerived = False
Attribute VB_Customizable = True
Attribute VB_Control = "CommandButton1, 3, 0, MSForms, CommandButton"
Private Sub CommandButton1_Click()

    '110/1/10 因近日從cnyes(Anue鉅亨)抓取日股價時，不時有抓不到現象，改可選擇從其他證券網站抓
    Dim arrData(1 To 520, 1 To 8)
    SName = "股價(日)2"
    股號 = Mid(Sheets("EPS預估與估價").Range("A1"), Len(Sheets("EPS預估與估價").Range("A1")) - 5, 4)
    MoneyDJ_TW_PRICE_New SName, 股號, "D"       '111/1/8 改用陣列，加快執行速度
    Range("B1").Select
    With Sheets("股價(日)2")
        RowEnd = .Range("S1").End(xlDown).Row
        LastYear = .Range("S" & RowEnd) - 1
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

End Sub
