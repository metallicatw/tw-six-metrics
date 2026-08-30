Attribute VB_Name = "工作表37"
Attribute VB_Base = "0{00020820-0000-0000-C000-000000000046}"
Attribute VB_GlobalNameSpace = False
Attribute VB_Creatable = False
Attribute VB_PredeclaredId = True
Attribute VB_Exposed = True
Attribute VB_TemplateDerived = False
Attribute VB_Customizable = True
Private Sub Worksheet_BeforeDoubleClick(ByVal Target As Range, Cancel As Boolean)

    Col = ActiveCell.Column
    Row = ActiveCell.Row
    EndRow = Cells(Rows.Count, "A").End(xlUp).Row
    If Col = 1 And Row >= 5 And Row <= EndRow Then
        Sheets("評價簡表").Activate
        Sheets("評價簡表").Select
        Sheets("評價簡表").Range("B1") = Target.Value
    End If

End Sub
