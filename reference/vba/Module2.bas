Attribute VB_Name = "Module2"
Sub 尋找儲存格錯誤()

    Dim Rng As Object
    Dim i As Integer
    For i = 1 To Sheets.Count
        For Each Rng In Sheets(i).Range(Sheets(i).Cells(1, 1), Sheets(i).Cells(1, 1).SpecialCells(xlLastCell))
            If IsError(Rng.Value) Then
                errval = Rng.Value
                Select Case errval
                    Case CVErr(xlErrDiv0)
                        Debug.Print Sheets(i).Name & " - " & Rng.Address & ": " & "#DIV/0!"
                    Case CVErr(xlErrNA)
                        Debug.Print Sheets(i).Name & " - " & Rng.Address & ": " & "#N/A"
                    Case CVErr(xlErrName)
                        Debug.Print Sheets(i).Name & " - " & Rng.Address & ": " & "#NAME?"
                    Case CVErr(xlErrNull)
                        Debug.Print Sheets(i).Name & " - " & Rng.Address & ": " & "#NULL!"
                    Case CVErr(xlErrNum)
                        Debug.Print Sheets(i).Name & " - " & Rng.Address & ": " & "#NUM!"
                    Case CVErr(xlErrRef)
                        Debug.Print Sheets(i).Name & " - " & Rng.Address & ": " & "#REF!"
                    Case CVErr(xlErrValue)
                        Debug.Print Sheets(i).Name & " - " & Rng.Address & ": " & "#VALUE!"
                End Select
            End If
        Next
    Next i

End Sub
