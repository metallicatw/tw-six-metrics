Attribute VB_Name = "工作表7"
Attribute VB_Base = "0{00020820-0000-0000-C000-000000000046}"
Attribute VB_GlobalNameSpace = False
Attribute VB_Creatable = False
Attribute VB_PredeclaredId = True
Attribute VB_Exposed = True
Attribute VB_TemplateDerived = False
Attribute VB_Customizable = True
Attribute VB_Control = "ComboBox1, 1, 0, MSForms, ComboBox"
Attribute VB_Control = "CommandButton1, 2, 1, MSForms, CommandButton"
Private Sub ComboBox1_Change()

    If Sheets("河流圖").Range("A2") = "Starting" Then
        Exit Sub
    End If
    Application.ScreenUpdating = False
    YearBgn = Sheets("河流圖").Range("J3") - 1
    With Sheets("股價(週)")
        .Range("A2:C1000").Cells.ClearContents
        .Range("AA2:AC1000").Cells.ClearContents
        RowBgn = WorksheetFunction.Match(YearBgn, .Range("S:S"), 1)
        RowEnd = .Range("S1").End(xlDown).Row
        .Range("S" & RowBgn & ":T" & RowEnd).Copy Destination:=.Range("A2")         '年度、日期
        .Range("X" & RowBgn & ":X" & RowEnd).Copy Destination:=.Range("C2")         '收盤價
        .Range("S" & RowBgn & ":T" & RowEnd).Copy Destination:=.Range("AA2")         '年度、日期
        .Range("X" & RowBgn & ":X" & RowEnd).Copy Destination:=.Range("AC2")         '收盤價
    End With
    Application.ScreenUpdating = True

End Sub

Private Sub CommandButton1_Click()

    設定圖表座標軸大小值 "河流圖"
    Range("A1").Select

End Sub
